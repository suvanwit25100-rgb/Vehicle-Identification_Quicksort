"use strict";
const { $, h, api, slotsView, candidateView, banner, topOf, pretty, when } = UI;
UI.initBar();
UI.initFoot();

const setStatus = (msg, err = false) => { const s = $("#status"); s.textContent = msg; s.className = "status-line" + (err ? " error" : ""); };
let depts = [];

function deptInfo() {
  const d = depts.find((x) => x.id === $("#department").value);
  $("#dept-info").textContent = d ? `Needs at least ${d.min_known_chars} readable characters and a score of ${d.match_threshold.toFixed(2)} or more to call a match.` : "";
}

/* ---------- results ---------- */
function framesTable(reads) {
  if (!reads.length) return h("p", { class: "empty" }, "No plate was located in any frame.");
  const head = h("tr", {}, h("th", {}, "Frame"), h("th", {}, "Sharp"), Array.from({ length: 10 }, (_, i) => h("th", {}, i + 1)));
  const rows = reads.map((fr) => h("tr", {}, h("td", { class: "mono" }, fr.frame_id), h("td", { class: "mono" }, Math.round(fr.sharpness)),
    fr.chars.map((c) => (c ? h("td", { class: "mono" }, c.char, h("small", {}, c.conf.toFixed(2))) : h("td", { class: "muted" }, "·")))));
  return h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, head), h("tbody", {}, rows)));
}

function trackView(jobId, t) {
  const m = t.match;
  const merged = (t.merged_from || []).length;
  return h("article", { class: "panel track" },
    h("div", { class: "track-h" },
      h("h3", {}, `Vehicle ${t.track_id} · ${t.vehicle_label}`),
      h("span", { class: "chip planned" }, `seen in ${t.frames_seen} frames`), h("span", { class: "chip planned" }, `plate in ${t.frames_with_plate}`),
      merged ? h("span", { class: "chip built", title: "Their plates agree on 6 or more characters and clash on none." }, `merged with track${merged > 1 ? "s" : ""} ${t.merged_from.join(", ")}`) : null),
    h("div", { class: "track-grid" },
      h("div", {},
        h("h4", {}, "Recovered plate"),
        slotsView(m.fused.slots),
        h("p", { class: "hint-s" }, "Amber ? positions were unreadable across frames and are reported as unknown, never guessed."),
        t.plate_crops.length ? h("div", { class: "crops" }, t.plate_crops.map((n) => h("img", { src: `/api/jobs/${jobId}/crops/${n}`, alt: `Plate crop ${n}`, loading: "lazy" }))) : null,
        h("p", { class: "attrs" }, `Colour: ${topOf(t.colour)} · Body type: ${topOf(t.body_type)}` + (t.max_plate_width_px ? ` · Largest plate: ${t.max_plate_width_px} px wide` : ""))),
      h("div", {}, banner(m),
        m.candidates.length ? h("h4", { style: "margin-top:22px" }, "Ranked candidates") : null,
        m.candidates.map((c, i) => candidateView(c, i + 1)))),
    h("details", { class: "frames-d" }, h("summary", {}, `Characters read in each frame (${t.frame_reads.length})`), framesTable(t.frame_reads)));
}

const isReadable = (t) => t.match.fused.slots.some((s) => s.char);

function unreadView(tracks) {
  const rows = tracks.map((t) => h("tr", {}, h("td", { class: "mono" }, t.track_id), h("td", {}, t.vehicle_label), h("td", { class: "mono" }, t.frames_seen), h("td", { style: "white-space:normal;min-width:260px" }, t.plate_note || "No readable plate characters.")));
  return h("details", { class: "panel unread" }, h("summary", {}, `${tracks.length} vehicle${tracks.length === 1 ? "" : "s"} without a readable plate`),
    h("div", { class: "tablewrap", style: "margin-top:16px" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Track"), h("th", {}, "Vehicle"), h("th", {}, "Frames"), h("th", {}, "Why no plate was read"))), h("tbody", {}, rows))));
}

function render(result) {
  const box = $("#results");
  const shown = result.tracks.filter(isReadable);
  const unread = result.tracks.filter((t) => !isReadable(t));
  box.replaceChildren(
    h("section", { class: "panel summary" },
      h("div", { class: "sum-top" }, h("h3", { style: "margin:0" }, "Analysis result"),
        h("a", { class: "btn sm", href: `/api/jobs/${result.job_id}/report`, target: "_blank", rel: "noopener" }, "Open printable report")),
      h("div", { class: "kpis", style: "margin-top:18px" },
        ...[[result.tracks.length, "vehicles tracked"], [shown.length, "with a readable plate"], [result.frames_sampled, "frames sampled"], [result.department.replace("_", " / ").toUpperCase(), "agency"]]
          .map(([n, l]) => h("div", { class: "kpi" }, h("div", { class: "n", style: typeof n === "string" ? "font-size:26px;padding-top:12px" : "" }, String(n)), h("div", { class: "l" }, l)))),
      h("p", { class: "hash" }, "Job ", h("span", { class: "mono" }, result.job_id), "  ·  SHA-256 ", h("span", { class: "mono" }, result.source_sha256))),
    ...(!result.tracks.length ? [h("section", { class: "panel" }, "No vehicles were tracked in this clip.")]
      : [...(shown.length ? shown.map((t) => trackView(result.job_id, t)) : [h("section", { class: "panel" }, "No plate could be read for any vehicle in this clip.")]),
         ...(unread.length ? [unreadView(unread)] : [])]));
  box.hidden = false;
  history.replaceState(null, "", `?job=${result.job_id}`);
  box.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- loading jobs, recent list ---------- */
async function openJob(id) {
  setStatus("Loading job…");
  try { render(await api(`/api/jobs/${encodeURIComponent(id)}`)); setStatus(""); }
  catch (e) { setStatus("Could not open job: " + e.message, true); }
}

async function loadRecent() {
  const box = $("#recent");
  try {
    const m = await api("/api/monitor");
    if (!m.jobs.recent.length) { box.replaceChildren(h("p", { class: "empty" }, "Nothing analysed yet. Upload a clip to start.")); return; }
    box.replaceChildren(...m.jobs.recent.slice(0, 5).map((j) => h("button", { class: "recent-item", type: "button", onclick: () => openJob(j.job_id) },
      h("span", { class: "mono" }, j.job_id), h("span", { class: "muted" }, `${j.readable} of ${j.tracks} readable`), h("span", { class: "plate-s mono" }, j.best_plate || "no plate"), h("span", { class: "muted" }, when(j.when)))));
  } catch (_) { box.replaceChildren(h("p", { class: "empty" }, "Recent jobs unavailable.")); }
}

/* ---------- upload ---------- */
const fileIn = $("#file"), drop = $("#drop");
function showFile() {
  const f = fileIn.files[0];
  $("#drop-title").textContent = f ? f.name : "Drop a clip here, or click to choose";
  $("#drop-sub").textContent = f ? `${(f.size / 1048576).toFixed(1)} MB, ready to analyse` : "MP4, AVI, MOV or MKV. About 40 seconds of footage is analysed.";
}
fileIn.addEventListener("change", showFile);
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) { fileIn.files = e.dataTransfer.files; showFile(); } });

$("#upload").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const file = fileIn.files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  fd.append("department", $("#department").value);
  $("#go").disabled = true;
  const t0 = Date.now();
  const tick = setInterval(() => { $("#status").innerHTML = `<span class="spinner"></span>Analysing… ${Math.round((Date.now() - t0) / 1000)} s. Longer clips take a minute or two on CPU.`; $("#status").className = "status-line"; }, 500);
  try { render(await api("/api/analyze", { method: "POST", body: fd })); setStatus("Done."); loadRecent(); }
  catch (e) { setStatus("Analysis failed: " + e.message, true); }
  finally { clearInterval(tick); $("#go").disabled = false; }
});
$("#lookup").addEventListener("submit", (ev) => { ev.preventDefault(); const id = $("#jobid").value.trim(); if (id) openJob(id); });

(async function init() {
  try {
    depts = await api("/api/departments");
    $("#department").replaceChildren(...depts.map((d) => h("option", { value: d.id }, d.name)));
    $("#department").addEventListener("change", deptInfo);
    deptInfo();
  } catch (e) { setStatus("Could not load agencies: " + e.message, true); }
  try {
    const brains = await api("/api/brains");
    $("#brains").replaceChildren(...brains.map((b) => h("span", { class: "chip " + (b.ready ? "ready" : "missing"), title: `${b.role} · ${b.source}` }, `${pretty(b.id)}: ${b.ready ? "ready" : "not installed"}`)));
  } catch (_) {}
  loadRecent();
  const id = new URLSearchParams(location.search).get("job");
  if (id) openJob(id);
})();
