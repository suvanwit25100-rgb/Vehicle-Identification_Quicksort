"use strict";
const { $, h, api, pretty, when } = UI;
UI.initBar();
UI.initFoot();

const AGENCY = { police: "Police", morth_nhai: "MoRTH / NHAI", bsf: "BSF", ssb: "SSB", customs: "Customs" };
const OUTCOME = [["match", "Match", "#3ddc97"], ["ambiguous", "Ambiguous", "#ffb454"], ["no_confident_match", "No confident match", "#ff2a3f"], ["insufficient_evidence", "Insufficient evidence", "#5c667d"]];
let calKey = "police";
let last = null;
let firstRender = true;

const hbars = (obj, labels = {}) => {
  const entries = Object.entries(obj).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return h("p", { class: "empty" }, "Nothing yet.");
  const max = Math.max(...entries.map((e) => e[1]));
  return h("div", {}, entries.map(([k, v]) => h("div", { class: "hbar" }, h("span", {}, labels[k] || pretty(k)), h("div", { class: "t" }, h("i", { style: `width:${(v / max) * 100}%` })), h("span", { class: "v" }, v))));
};

function kpis(m) {
  const j = m.jobs;
  const items = [[j.total, "analyses run", `${j.frames_sampled} frames sampled`], [j.tracks, "vehicles tracked", "across all analyses"],
    [j.tracks_readable, "plates read", `${j.tracks ? Math.round((j.tracks_readable / j.tracks) * 100) : 0}% of vehicles had any readable character`],
    [m.complaints.total, "citizen reports", "filed through the public form"], [m.registry_rows, "registry rows", "synthetic demo registry"]];
  $("#kpis").replaceChildren(...items.map(([n, l, d]) => {
    const num = h("div", { class: "n" }, String(n));
    if (firstRender) UI.countUp(num, n);   // count up once; later refreshes just update the numbers
    return h("div", { class: "kpi" }, num, h("div", { class: "l" }, l), h("div", { class: "d" }, d));
  }));
}

function outcomes(m) {
  const o = m.jobs.outcomes, total = Object.values(o).reduce((a, b) => a + b, 0);
  if (!total) { $("#outcomes").replaceChildren(h("p", { class: "empty" }, "No vehicles analysed yet.")); return; }
  $("#outcomes").replaceChildren(
    h("div", { class: "stack", role: "img", "aria-label": OUTCOME.map(([k, l]) => `${l}: ${o[k]}`).join(", ") }, OUTCOME.map(([k, , c]) => h("i", { style: `width:${(o[k] / total) * 100}%;background:${c}` }))),
    h("div", { class: "legend" }, OUTCOME.map(([k, l, c]) => h("span", { style: `--c:${c}` }, `${l} ${o[k]}`))),
    h("p", { class: "muted", style: "font-size:13px;margin-top:16px" }, "Most vehicles in real footage have no readable plate, which is why “insufficient evidence” dominates. The system says so instead of guessing."));
}

function histogram(m) {
  const hist = m.jobs.known_chars_hist, max = Math.max(1, ...hist);
  $("#hist").replaceChildren(
    h("div", { class: "vhist", role: "img", "aria-label": "Vehicles by number of characters recovered" }, hist.map((n, i) => h("div", { class: "vcol" }, h("span", { class: "vn" }, n || ""), h("i", { style: `height:${(n / max) * 100}%` }), h("span", { class: "vl" }, i)))),
    h("p", { class: "muted", style: "font-size:13px;margin-top:12px" }, "Horizontal axis: how many of the 10 plate characters were recovered. 0 means the plate stayed unknown."));
}

function calibration(m, animate = false) {
  const cal = m.calibration;
  if (!cal) { $("#cal-chart").replaceChildren(h("p", { class: "empty" }, "No calibration report found. Run scripts/calibrate.py.")); return; }
  const keys = Object.keys(cal);
  $("#cal-tabs").replaceChildren(...keys.map((k) => h("button", { role: "tab", "aria-selected": String(k === calKey), onclick: () => { calKey = k; calibration(last, true); } }, AGENCY[k] || k)));
  const c = cal[calKey], sw = c.sweep, W = 560, H = 290, L = 44, B = 50, T = 12, R = 14;
  const x0 = sw[0].theta, x1 = sw[sw.length - 1].theta;
  const X = (t) => L + ((t - x0) / (x1 - x0)) * (W - L - R), Y = (v) => H - B - v * (H - B - T);
  const line = (key) => sw.map((s) => `${X(s.theta).toFixed(1)},${Y(s[key]).toFixed(1)}`).join(" ");
  const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "calsvg" + (animate ? " redraw" : "")); svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Recall and false-match rate against threshold for ${AGENCY[calKey] || calKey}`);
  const grid = [0, .25, .5, .75, 1].map((v) => `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="rgba(255,255,255,.08)"/><text x="${L - 8}" y="${Y(v) + 4}" fill="#8f99b0" font-size="11" text-anchor="end">${Math.round(v * 100)}%</text>`).join("");
  const ticks = sw.filter((_, i) => i % 2 === 0).map((s) => `<text x="${X(s.theta)}" y="${H - B + 18}" fill="#8f99b0" font-size="11" text-anchor="middle">${s.theta.toFixed(2)}</text>`).join("");
  const mark = (t, col, label, dy) => `<line x1="${X(t)}" x2="${X(t)}" y1="${T}" y2="${H - B}" stroke="${col}" stroke-dasharray="3 3"/><text x="${X(t) + 5}" y="${T + dy}" fill="${col}" font-size="11">${label}</text>`;
  svg.innerHTML = `${grid}${ticks}<line x1="${L}" x2="${W - R}" y1="${Y(c.target_fmr)}" y2="${Y(c.target_fmr)}" stroke="#3ddc97" stroke-dasharray="2 4"/>
    <text x="${W - R}" y="${Y(c.target_fmr) - 5}" fill="#3ddc97" font-size="11" text-anchor="end">false-match target ${Math.round(c.target_fmr * 100)}%</text>
    <polyline fill="none" stroke="#ffb454" stroke-width="1.6" stroke-dasharray="1 4" stroke-linecap="round" points="${line("lookalike_false_match")}"/>
    <polyline fill="none" stroke="#8f99b0" stroke-width="2" stroke-dasharray="5 3" points="${line("false_match_upper95")}"/>
    <polyline fill="none" stroke="#ff2a3f" stroke-width="2.4" points="${line("recall_top1")}"/>
    ${mark(c.current.theta, "#8f99b0", "earlier " + c.current.theta.toFixed(2), 14)}${mark(c.recommended.theta, "#ff2a3f", "chosen " + c.recommended.theta.toFixed(2), 28)}
    <text x="${(L + W - R) / 2}" y="${H - 6}" fill="#8f99b0" font-size="11" text-anchor="middle">threshold θ (score needed to call a match)</text>`;
  const key = (col, txt, dash) => h("span", { style: `--c:${col}` }, txt);
  $("#cal-chart").replaceChildren(svg, h("div", { class: "legend" }, key("#ff2a3f", "Recall of the right vehicle (top 1)"), key("#8f99b0", "False matches, 95% upper bound"), key("#ffb454", "False matches on look-alike plates")));
  const pct = (v) => `${(v * 100).toFixed(1)}%`;
  const row = (label, o) => h("tr", {}, h("td", {}, label), h("td", { class: "mono" }, o.theta.toFixed(2)), h("td", { class: "mono" }, pct(o.recall_top1)), h("td", { class: "mono" }, pct(o.false_match_upper95)), h("td", { class: "mono" }, pct(o.lookalike_false_match)));
  $("#cal-table").replaceChildren(h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["", "θ", "Recall", "False ≤", "Look-alike"].map((t) => h("th", {}, t)))), h("tbody", {}, row("Earlier", c.current), row("Chosen", c.recommended)))),
    h("p", { class: "muted", style: "font-size:13px;margin-top:14px" }, `${AGENCY[calKey] || calKey} accepts at most ${Math.round(c.target_fmr * 100)}% false matches. Raising the threshold lowers false matches and also recall, so the chosen value is the lowest one that meets the target.`));
}

function brains(m) {
  $("#brains").replaceChildren(...m.brains.map((b) => h("div", { class: "brain" }, h("div", { class: "brain-h" }, h("strong", {}, pretty(b.id)), h("span", { class: "chip " + (b.ready ? "ready" : "missing") }, b.ready ? "ready" : "not installed")),
    h("p", { class: "muted" }, b.role), h("p", { class: "dim" }, `${b.source} · ${b.license}${b.required ? "" : " · optional"}`))));
}

function recent(m) {
  const r = m.jobs.recent;
  if (!r.length) { $("#recent").replaceChildren(h("p", { class: "empty" }, "No analyses yet. Upload a clip in the console.")); return; }
  $("#recent").replaceChildren(h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Job", "When", "Agency", "Vehicles", "Readable", "Best plate", ""].map((t) => h("th", {}, t)))),
    h("tbody", {}, r.map((j) => h("tr", {}, h("td", { class: "mono" }, h("a", { href: `/console/?job=${j.job_id}` }, j.job_id)), h("td", {}, when(j.when)), h("td", {}, AGENCY[j.department] || j.department), h("td", { class: "mono" }, j.tracks), h("td", { class: "mono" }, j.readable), h("td", { class: "mono" }, j.best_plate || "·"),
      h("td", {}, h("a", { href: `/api/jobs/${j.job_id}/report`, target: "_blank", rel: "noopener" }, "report ↗"))))))));
}

function render(m) {
  last = m;
  kpis(m); outcomes(m); histogram(m);
  $("#by-dept").replaceChildren(hbars(m.jobs.by_department, AGENCY));
  const c = m.complaints;
  $("#complaints").replaceChildren(c.total ? h("div", {}, h("p", { class: "muted", style: "font-size:12px;letter-spacing:.12em;text-transform:uppercase;margin-bottom:6px" }, "By status"), hbars(c.by_status, UI.STATUS_LABEL),
    h("p", { class: "muted", style: "font-size:12px;letter-spacing:.12em;text-transform:uppercase;margin:16px 0 6px" }, "By agency"), hbars(c.by_department, AGENCY)) : h("p", { class: "empty" }, "No reports filed yet. Citizens can file one from “Report an issue”."));
  calibration(m); brains(m); recent(m);
  $("#updated").textContent = `Updated ${when(m.generated_at)}. Refreshes every 20 seconds.`;
  if (firstRender) { firstRender = false; setTimeout(() => { document.querySelector("main").dataset.settled = ""; }, 400); }
}

async function refresh() {
  try { render(await api("/api/monitor")); }
  catch (e) { $("#updated").textContent = "Could not reach the backend: " + e.message; $("#updated").className = "status-line error"; }
}
refresh();
setInterval(refresh, 20000);
