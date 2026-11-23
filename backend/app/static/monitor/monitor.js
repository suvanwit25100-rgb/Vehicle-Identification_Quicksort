"use strict";
/* Everything on this page comes from GET /api/monitor, which reads saved analyses, citizen reports, model files, this server's own
   request counters and the machine. Each panel says what its numbers were drawn from. */
const { $, h, api, pretty, when } = UI;
UI.initBar();
UI.initFoot();

const AGENCY = { police: "Police", morth_nhai: "MoRTH / NHAI", bsf: "BSF", ssb: "SSB", customs: "Customs" };
const OUTCOME = [["match", "Match", "#3ddc97"], ["ambiguous", "Ambiguous", "#ffb454"], ["no_confident_match", "No confident match", "#ff2a3f"], ["insufficient_evidence", "Insufficient evidence", "#5c667d"]];
let firstRender = true;

const fmtDur = (s) => { s = Math.round(s); const m = Math.floor(s / 60), d = Math.floor(m / 60), hr = Math.floor(d / 24); return hr ? `${hr}d ${d % 24}h` : d ? `${d}h ${m % 60}m` : m ? `${m}m ${s % 60}s` : `${s}s`; };
const fmtBytes = (b) => (b >= 1073741824 ? `${(b / 1073741824).toFixed(1)} GB` : b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(0, Math.round(b / 1024))} KB`);
const src = (id, text) => { const e = $("#" + id); if (e) e.textContent = text; };
const none = (t) => h("p", { class: "empty" }, t);
const pl = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const row = (a, b) => h("div", { class: "mini", style: "padding:6px 0;border-bottom:1px solid var(--rule)" }, h("span", {}, a), h("b", {}, b));

const hbars = (obj, labels = {}) => {
  const entries = Object.entries(obj).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return none("Nothing yet.");
  const max = Math.max(...entries.map((e) => e[1]));
  return h("div", {}, entries.map(([k, v]) => h("div", { class: "hbar" }, h("span", {}, labels[k] || pretty(k)), h("div", { class: "t" }, h("i", { style: `width:${(v / max) * 100}%` })), h("span", { class: "v" }, v))));
};

const vbars = (items, label, aria) => {
  const max = Math.max(1, ...items.map((i) => i.n));
  return h("div", { class: "vhist", role: "img", "aria-label": aria }, items.map((i) => h("div", { class: "vcol" }, h("span", { class: "vn" }, i.n || ""), h("i", { style: `height:${(i.n / max) * 100}%` }), h("span", { class: "vl" }, label(i)))));
};

function kpis(m) {
  const j = m.jobs, bytes = m.host.jobs_bytes + m.host.complaints_bytes;
  const items = [
    [j.total, "analyses run", `of ${pl(j.distinct_videos, "distinct video")} · ${j.frames_sampled.toLocaleString()} frames sampled`],
    [j.tracks, "vehicles tracked", "across all analyses"],
    [j.tracks_readable, "plates read", j.tracks ? `${Math.round((j.tracks_readable / j.tracks) * 100)}% of vehicles had a readable character` : "nothing analysed yet"],
    [j.footage_seconds ? fmtDur(j.footage_seconds) : "0s", "footage analysed", `${pl(j.stored_videos, "original video")} kept`],
    [m.complaints.total, "citizen reports", "filed through the public form"],
    [fmtBytes(bytes), "stored on the server", "analyses, images and reports"],
  ];
  $("#kpis").replaceChildren(...items.map(([n, l, d]) => {
    const num = h("div", { class: "n", style: typeof n === "string" ? "font-size:clamp(24px,2.6vw,36px);padding-top:8px" : "" }, String(n));
    if (firstRender && typeof n === "number") UI.countUp(num, n);   // count up once; later refreshes just update the numbers
    return h("div", { class: "kpi" }, num, h("div", { class: "l" }, l), h("div", { class: "d" }, d));
  }));
}

function outcomes(m) {
  const o = m.jobs.outcomes, total = Object.values(o).reduce((a, b) => a + b, 0), c = m.jobs.cross_check, ct = c.agrees + c.disagrees + c.inconclusive;
  src("src-outcomes", `From ${pl(total, "vehicle")} in ${pl(m.jobs.total, "stored analysis").replace("analysiss", "analyses")}.`);
  if (!total) { $("#outcomes").replaceChildren(none("No vehicles analysed yet.")); return; }
  const parts = [["agrees", "Agrees", "#3ddc97"], ["disagrees", "Disagrees", "#ff2a3f"], ["inconclusive", "Inconclusive", "#ffb454"]];
  $("#outcomes").replaceChildren(
    h("div", { class: "stack", role: "img", "aria-label": OUTCOME.map(([k, l]) => `${l}: ${o[k]}`).join(", ") }, OUTCOME.map(([k, , col]) => h("i", { style: `width:${(o[k] / total) * 100}%;background:${col}` }))),
    h("div", { class: "legend" }, OUTCOME.map(([k, l, col]) => h("span", { style: `--c:${col}` }, `${l} ${o[k]}`))),
    ct ? h("div", { style: "margin-top:24px" }, h("p", { class: "label-s" }, `Second reader, on ${pl(ct, "vehicle")} with a readable plate`),
      h("div", { class: "stack", role: "img", "aria-label": parts.map(([k, l]) => `${l}: ${c[k]}`).join(", ") }, parts.map(([k, , col]) => h("i", { style: `width:${(c[k] / ct) * 100}%;background:${col}` }))),
      h("div", { class: "legend" }, parts.map(([k, l, col]) => h("span", { style: `--c:${col}` }, `${l} ${c[k]}`)))) : null);
}

function histogram(m) {
  const hist = m.jobs.known_chars_hist, tot = hist.reduce((a, b) => a + b, 0);
  src("src-hist", `From ${pl(tot, "vehicle")}. Horizontal axis: how many of the 10 plate characters were recovered; 0 means the plate stayed unknown.`);
  $("#hist").replaceChildren(tot ? vbars(hist.map((n, i) => ({ n, i })), (i) => i.i, "Vehicles by number of characters recovered") : none("No vehicles analysed yet."));
}

function widthPanel(m) {
  const bins = m.jobs.plate_width, tot = bins.reduce((a, b) => a + b.vehicles, 0);
  src("src-width", `From ${pl(tot, "vehicle")} whose plate was located. The largest plate width seen for each vehicle, against how much of the plate was recovered.`);
  if (!tot) { $("#width").replaceChildren(none("No plates have been located yet.")); return; }
  const max = Math.max(...bins.map((b) => b.vehicles));
  $("#width").replaceChildren(
    ...bins.map((b) => h("div", { class: "wrow" }, h("span", {}, b.bin),
      h("div", { class: "stack", style: `width:${Math.max(6, (b.vehicles / max) * 100)}%`, role: "img", "aria-label": `${b.bin}: ${b.vehicles} vehicles, ${b.most} with 8 or more characters` },
        h("i", { style: `width:${b.vehicles ? (b.most / b.vehicles) * 100 : 0}%;background:#3ddc97` }), h("i", { style: `width:${b.vehicles ? ((b.any - b.most) / b.vehicles) * 100 : 0}%;background:#ffb454` }), h("i", { style: `width:${b.vehicles ? ((b.vehicles - b.any) / b.vehicles) * 100 : 0}%;background:#5c667d` })),
      h("span", { class: "v" }, `${b.most}/${b.vehicles}`))),
    h("div", { class: "legend" }, h("span", { style: "--c:#3ddc97" }, "8 or more characters"), h("span", { style: "--c:#ffb454" }, "1 to 7"), h("span", { style: "--c:#5c667d" }, "none")));
}

function confPanel(m) {
  const hist = m.jobs.confidence_hist, tot = hist.reduce((a, b) => a + b.count, 0);
  src("src-conf", `From ${tot.toLocaleString()} recovered characters. How sure the reader was of each one.`);
  $("#conf").replaceChildren(tot ? vbars(hist.map((b) => ({ n: b.count, b })), (i) => `${i.b.from.toFixed(1)}`, "Recovered characters by confidence") : none("No characters recovered yet."));
}

function daysPanel(m) {
  const d = m.jobs.per_day;
  src("src-days", d.length ? `From stored analyses, last ${pl(d.length, "day")} with activity.` : "From stored analyses.");
  $("#days").replaceChildren(d.length ? vbars(d.map((x) => ({ n: x.analyses, x })), (i) => i.x.date.slice(5).replace("-", "/"), "Analyses per day") : none("No analyses yet."));
}

function procPanel(m) {
  const p = m.jobs.processing, j = m.jobs;
  src("src-proc", `From ${pl(p.count, "analysis").replace("analysiss", "analyses")} with timing recorded (older ones were saved before timing existed).`);
  $("#proc").replaceChildren(p.count ? h("div", {}, row("Median time per video", `${p.median_s} s`), row("Slowest", `${p.max_s} s`),
    row("Footage analysed", fmtDur(j.footage_seconds)), p.realtime_factor != null ? row("Median speed", `${p.realtime_factor}× the footage length`) : null,
    h("p", { class: "cap", style: "margin-top:10px" }, "Measured on this machine, on CPU. Above 1× means analysis takes longer than the video lasts.")) : none("No timed analyses yet."));
}

function serverPanel(m) {
  const s = m.server, hs = m.host;
  src("src-server", `Counted since the server started ${when(s.started_at)}. Not including this page's own refreshes.`);
  const load = hs.load_1m != null ? `${hs.load_1m} · ${hs.load_5m} · ${hs.load_15m}` : null;
  $("#server").replaceChildren(h("div", {},
    row("Up for", fmtDur(s.uptime_s)), row("Requests served", s.total.toLocaleString()), row("Client errors (4xx)", s.client_errors), row("Server errors (5xx)", s.server_errors),
    Object.keys(s.by_group).length ? h("div", { style: "margin:14px 0 6px" }, h("p", { class: "label-s" }, "By kind"), hbars(s.by_group)) : null,
    h("p", { class: "label-s", style: "margin-top:16px" }, "This machine"),
    row("CPUs", hs.cpus ?? "unknown"), load ? row("Load (1 · 5 · 15 min)", load) : null,
    hs.peak_memory_mb != null ? row("Peak memory of the server", `${hs.peak_memory_mb} MB`) : null,
    hs.disk_total_gb != null ? row("Disk free", `${hs.disk_free_gb} of ${hs.disk_total_gb} GB`) : null, row("System", `${hs.system}, Python ${hs.python}`)));
}

function complaintsPanel(m) {
  const c = m.complaints;
  src("src-complaints", `From ${pl(c.total, "report")} stored on this server.`);
  $("#complaints").replaceChildren(c.total ? h("div", {}, h("p", { class: "label-s" }, "By status"), hbars(c.by_status, UI.STATUS_LABEL),
    h("p", { class: "label-s", style: "margin-top:16px" }, "By agency"), hbars(c.by_department, AGENCY)) : none("No reports filed yet. Citizens can file one from “Report an issue”."));
}

function brains(m) {
  $("#brains").replaceChildren(...m.brains.map((b) => h("div", { class: "brain" }, h("div", { class: "brain-h" }, h("strong", {}, pretty(b.id)), h("span", { class: "chip " + (b.ready ? "ready" : "missing") }, b.ready ? "ready" : "not installed")),
    h("p", { class: "muted" }, b.role), h("p", { class: "dim" }, `${b.source} · ${b.license}${b.required ? "" : " · optional"}`))));
}

function recent(m) {
  const r = m.jobs.recent;
  src("src-recent", r.length ? `The ${r.length} most recent of ${pl(m.jobs.total, "stored analysis").replace("analysiss", "analyses")}. Open the Archive for all of them.` : "");
  if (!r.length) { $("#recent").replaceChildren(none("No analyses yet. Upload a clip in the console.")); return; }
  $("#recent").replaceChildren(h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Job", "File", "When", "Agency", "Vehicles", "Readable", "Best plate", ""].map((t) => h("th", {}, t)))),
    h("tbody", {}, r.map((j) => h("tr", {}, h("td", { class: "mono" }, h("a", { href: `/console/?job=${j.job_id}` }, j.job_id)), h("td", { style: "max-width:170px;overflow:hidden;text-overflow:ellipsis" }, j.filename || "·"), h("td", {}, when(j.when)), h("td", {}, AGENCY[j.department] || j.department), h("td", { class: "mono" }, j.tracks), h("td", { class: "mono" }, j.readable), h("td", { class: "mono" }, j.best_plate || "·"),
      h("td", { style: "white-space:nowrap" }, h("a", { href: `/api/jobs/${j.job_id}/report`, target: "_blank", rel: "noopener" }, "report ↗"), "  ", h("a", { href: `/api/jobs/${j.job_id}/download`, download: `case-${j.job_id}.zip` }, "zip ↓"))))))));
}

function render(m) {
  kpis(m); outcomes(m); histogram(m); widthPanel(m); confPanel(m); daysPanel(m); procPanel(m); serverPanel(m); complaintsPanel(m); brains(m); recent(m);
  const d = Object.keys(m.jobs.by_department).length ? m.jobs.by_department : {};
  src("src-dept", `From ${pl(m.jobs.total, "stored analysis").replace("analysiss", "analyses")}.`);
  $("#by-dept").replaceChildren(hbars(d, AGENCY));
  $("#updated").textContent = `Updated ${when(m.generated_at)}. Refreshes every 20 seconds.`;
  $("#updated").className = "status-line";
  if (firstRender) { firstRender = false; setTimeout(() => { document.querySelector("main").dataset.settled = ""; }, 400); }
}

async function refresh() {
  try { render(await api("/api/monitor")); }
  catch (e) { $("#updated").textContent = "Could not reach the backend: " + e.message; $("#updated").className = "status-line error"; }
}
refresh();
setInterval(refresh, 20000);
