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

const VERDICT = { agrees: "agrees", disagrees: "disagrees, verify manually", inconclusive: "inconclusive" };
function secondView(t) {
  const s = t.second_reader;
  if (!s) return null;
  const known = t.match.fused.slots.filter((x) => x.char).length;   // the API sends slots, not a count
  return h("div", { class: `second ${s.verdict}` },
    h("b", {}, "Second reader "), h("span", { class: "mono" }, s.reading || "read nothing"), ` ${VERDICT[s.verdict]}`,
    h("span", { class: "muted" }, s.verdict === "inconclusive" ? "" : ` · ${s.agree} of ${known} known characters confirmed, ${s.clash} clash`),
    h("small", {}, `${s.reader}. It never changes the recovered plate or fills a ? in.`));
}
function wholeReads(t) {
  const counts = {};
  t.frame_reads.forEach((f) => { if (f.raw && f.raw.length >= 6) counts[f.raw] = (counts[f.raw] || 0) + 1; });
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 3);
  return top.length ? h("p", { class: "attrs" }, "Whole-plate reads before fitting to ten slots: ", ...top.map(([r, n], i) => [i ? " · " : "", h("span", { class: "mono" }, r), h("span", { class: "muted" }, ` ×${n}`)])) : null;
}

const ACTION_TONE = { alert: "bad", refer: "warn", document: "warn", verify: "warn", note: "", clear: "" };
async function draftChallan(jobId, trackId, btn, out) {
  let token = "";
  try { token = sessionStorage.getItem("officerToken") || ""; } catch (e) { /* storage blocked */ }
  if (!token) { out.textContent = "Sign in on the Officer portal first: a draft challan needs an officer sign-in."; return; }
  btn.disabled = true; out.textContent = "Preparing the draft…";
  try {
    const r = await fetch(`/api/desk/jobs/${jobId}/tracks/${trackId}/challan.pdf`, { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) throw new Error(r.status === 401 ? "Your officer session ended. Sign in again on the Officer portal." : ((await r.json().catch(() => ({}))).detail || `Failed (${r.status})`));
    window.open(URL.createObjectURL(await r.blob()), "_blank", "noopener");
    out.textContent = "Draft opened in a new tab. It is a draft for an officer to check; nothing was sent.";
  } catch (e) { out.textContent = e.message; } finally { btn.disabled = false; }
}
let flagCategories = null;
async function categories() {
  if (!flagCategories) flagCategories = await api("/api/complaints/categories");
  return flagCategories;
}
function flagView(jobId, t, flags, result) {
  const box = h("div", { class: "flagbox" });
  const done = (id) => box.replaceChildren(h("p", { class: "flagged" }, h("b", {}, "Flagged. "), `Filed as report `, h("span", { class: "mono" }, id),
    ". It is now in the reporting section for an officer to review: ", h("a", { href: "/officer/#/reports/" + id }, "open it in the officer portal"), "."));
  if (flags[t.track_id]) { done(flags[t.track_id]); return box; }
  const open = h("button", { class: "btn sm", type: "button" }, "Flag this vehicle");
  open.addEventListener("click", async () => {
    open.disabled = true;
    let cats = [];
    try { cats = await categories(); } catch (e) { box.append(h("p", { class: "err" }, "Could not load the report types: " + e.message)); open.disabled = false; return; }
    const plate = t.match.fused.slots.map((s) => (s.char && s.char !== "-" ? s.char : s.char ? "" : "?")).join("");
    const cat = h("select", { "aria-label": "What is being flagged" }, h("option", { value: "" }, "Choose one…"), ...cats.map((c) => h("option", { value: c.id }, c.label)));
    const desc = h("textarea", { maxlength: 1000, rows: 3, "aria-label": "What was seen" }, `Seen in analysed footage${result.source_filename ? ` (${result.source_filename})` : ""}, vehicle ${t.track_id}, plate read as ${plate}. `);
    const where = h("input", { type: "text", maxlength: 200, placeholder: "Where was this filmed? (road, junction, camera)", "aria-label": "Where it was filmed" });
    const msg = h("p", { class: "status-line", role: "status", "aria-live": "polite" });
    const send = h("button", { class: "btn primary sm", type: "button" }, "File the report");
    const cancel = h("button", { class: "btn sm", type: "button" }, "Cancel");
    cancel.addEventListener("click", () => box.replaceChildren(open) || (open.disabled = false));
    send.addEventListener("click", async () => {
      if (!cat.value) { msg.textContent = "Choose what you are flagging."; msg.className = "status-line error"; return; }
      if (desc.value.trim().length < 5) { msg.textContent = "Say what was seen (a few words)."; msg.className = "status-line error"; return; }
      if (where.value.trim().length < 3) { msg.textContent = "Say where this was filmed."; msg.className = "status-line error"; return; }
      send.disabled = true; msg.textContent = "Filing…"; msg.className = "status-line";
      try {
        const r = await api(`/api/jobs/${jobId}/tracks/${t.track_id}/flag`, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category: cat.value, description: desc.value.trim(), location_text: where.value.trim(), observed_at: result.created_at || null }) });
        done(r.complaint_id);
      } catch (e) { msg.textContent = e.message; msg.className = "status-line error"; send.disabled = false; }
    });
    box.replaceChildren(h("div", { class: "flagform" }, h("label", {}, "What are you flagging", cat), h("label", {}, "What was seen", desc), h("label", {}, "Where", where),
      h("p", { class: "hint-s" }, "This files a report on the officer desk with the evidence frame and the fused plate. It is a lead for an officer to check, not an accusation."),
      h("div", { class: "row-btns" }, send, cancel), msg));
  });
  box.append(open);
  return box;
}

function actionsView(jobId, t, acts) {
  if (!acts || !acts.length) return null;
  return h("div", { class: "agency-actions" }, h("h4", { style: "margin-top:22px" }, "Suggested next steps"),
    acts.map((a) => { const out = h("span", { class: "muted", style: "font-size:12.5px" });
      const btn = a.challan ? h("button", { class: "btn sm", type: "button" }, "Draft e-challan (PDF)") : null;
      if (btn) btn.addEventListener("click", () => draftChallan(jobId, t.track_id, btn, out));
      return h("div", { class: `act ${ACTION_TONE[a.kind] || ""}` }, h("b", {}, a.title), h("p", { class: "muted", style: "margin:4px 0 8px;font-size:13.5px" }, a.detail), btn, btn ? h("div", {}, out) : null); }));
}

function compareView(jobId, t) {
  const input = h("input", { type: "text", maxlength: "10", placeholder: "e.g. WB06A8292 or WB06??8292", "aria-label": "A plate to compare with", class: "mono", style: "text-transform:uppercase;max-width:220px" });
  const out = h("div", { class: "cmp-out" });
  const btn = h("button", { class: "btn sm", type: "button" }, "Compare");
  const go = async () => {
    btn.disabled = true; out.replaceChildren();
    try {
      const r = await api(`/api/jobs/${encodeURIComponent(jobId)}/tracks/${t.track_id}/compare`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plate: input.value }) });
      out.append(r.score === null ? h("p", { class: "muted" }, r.message) : h("div", {},
        h("div", { class: "cmp-score" }, h("span", { class: "num" }, r.score.toFixed(2)), h("span", { class: "lab" }, `Fit with ${r.typed}`)),
        h("p", { class: "muted", style: "font-size:13px" }, r.message)));
    } catch (e) { out.append(h("p", { class: "err" }, e.message)); } finally { btn.disabled = false; }
  };
  btn.addEventListener("click", go);
  input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); go(); } });
  return h("div", { class: "cmp" }, h("h4", { style: "margin-top:22px" }, "Compare with a plate you have"),
    h("p", { class: "muted", style: "font-size:13px;margin:0 0 8px" }, "Type a plate from a witness or a suspect (? for unknown characters). Scores how well the plate we recovered fits it. Plate evidence only, not a registry search."),
    h("div", { style: "display:flex;gap:8px;flex-wrap:wrap" }, input, btn), out);
}

function trackView(jobId, t, acts, flags, result) {
  const m = t.match;
  const merged = (t.merged_from || []).length;
  return h("article", { class: "panel track" },
    h("div", { class: "track-h" },
      h("h3", {}, `Vehicle ${t.track_id} · ${t.vehicle_label}`),
      h("span", { class: "chip planned" }, `seen in ${t.frames_seen} frames`), h("span", { class: "chip planned" }, `plate in ${t.frames_with_plate}`),
      t.plate_layout === "two-row" ? h("span", { class: "chip built", title: "Typical of two-wheelers: each row was read as its own line, then joined." }, "two-row plate") : null,
      merged ? h("span", { class: "chip built", title: "Their plates agree on 6 or more characters and clash on none." }, `merged with track${merged > 1 ? "s" : ""} ${t.merged_from.join(", ")}`) : null),
    h("div", { class: "track-grid" },
      h("div", {},
        h("h4", {}, "Recovered plate"),
        slotsView(m.fused.slots),
        h("p", { class: "hint-s" }, "Amber ? positions were unreadable across frames and are reported as unknown, never guessed."),
        secondView(t),
        t.plate_crops.length ? h("div", { class: "crops" }, t.plate_crops.map((n) => h("img", { src: `/api/jobs/${jobId}/crops/${n}`, alt: `Plate crop ${n}`, loading: "lazy" }))) : null,
        wholeReads(t),
        h("p", { class: "attrs" }, `Colour: ${topOf(t.colour)} · Body type: ${topOf(t.body_type)}` + (t.max_plate_width_px ? ` · Largest plate: ${t.max_plate_width_px} px wide` : "")),
        (t.evidence_frame || t.vehicle_crop) ? h("div", { class: "media" },
          t.evidence_frame ? h("a", { href: `/api/jobs/${jobId}/crops/${t.evidence_frame}`, target: "_blank", rel: "noopener", title: "Open the full frame" }, h("img", { class: "evimg", src: `/api/jobs/${jobId}/crops/${t.evidence_frame}`, alt: `Frame the plate of vehicle ${t.track_id} was read from`, loading: "lazy" })) : null,
          t.vehicle_crop ? h("img", { class: "vehimg", src: `/api/jobs/${jobId}/crops/${t.vehicle_crop}`, alt: `Vehicle ${t.track_id}`, loading: "lazy" }) : null) : null),
      h("div", {}, banner(m), compareView(jobId, t),
        m.candidates.length ? h("h4", { style: "margin-top:22px" }, "Ranked candidates") : null,
        m.candidates.map((c, i) => candidateView(c, i + 1)), actionsView(jobId, t, acts),
        h("h4", { style: "margin-top:22px" }, "Flag"), flagView(jobId, t, flags, result))),
    h("details", { class: "frames-d" }, h("summary", {}, `Characters read in each frame (${t.frame_reads.length})`), framesTable(t.frame_reads)));
}

const isReadable = (t) => t.match.fused.slots.some((s) => s.char && s.char !== "-");

function unreadView(tracks, advice = {}) {
  const rows = tracks.map((t) => h("tr", {}, h("td", { class: "mono" }, t.track_id), h("td", {}, t.vehicle_label), h("td", { class: "mono" }, t.frames_seen),
    h("td", { style: "white-space:normal;min-width:260px" }, t.plate_note || "No readable plate characters.", (advice[t.track_id] || []).slice(0, 1).map((x) => h("small", { style: "display:block;color:var(--muted);margin-top:4px" }, "What would help: " + x)))));
  return h("details", { class: "panel unread" }, h("summary", {}, `${tracks.length} vehicle${tracks.length === 1 ? "" : "s"} without a readable plate`),
    h("div", { class: "tablewrap", style: "margin-top:16px" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Track"), h("th", {}, "Vehicle"), h("th", {}, "Frames"), h("th", {}, "Why no plate was read"))), h("tbody", {}, rows))));
}

async function render(result) {
  let acts = {}, flags = {}, advice = { tracks: {}, summary: [] };
  try { advice = await api(`/api/jobs/${encodeURIComponent(result.job_id)}/advice`); } catch (e) { /* advice is optional */ }
  try { flags = await api(`/api/jobs/${encodeURIComponent(result.job_id)}/flags`); } catch (e) { /* flags are optional */ }
  try { acts = (await api(`/api/jobs/${encodeURIComponent(result.job_id)}/actions`)).actions || {}; } catch (e) { /* suggestions are optional */ }
  const box = $("#results");
  const shown = result.tracks.filter(isReadable);
  const unread = result.tracks.filter((t) => !isReadable(t));
  box.replaceChildren(
    h("section", { class: "panel summary" },
      h("div", { class: "sum-top" }, h("h3", { style: "margin:0" }, "Analysis result"),
        h("div", { class: "row-btns", style: "margin:0" },
          h("a", { class: "btn primary sm", href: `/api/jobs/${result.job_id}/download`, download: `case-${result.job_id}.zip` }, "Download full report (ZIP)"),
          h("a", { class: "btn sm", href: `/api/jobs/${result.job_id}/report`, target: "_blank", rel: "noopener" }, "Open printable report"),
          h("a", { class: "btn sm", href: `/api/jobs/${result.job_id}/report.pdf`, target: "_blank", rel: "noopener" }, "PDF"))),
      h("div", { class: "kpis", style: "margin-top:18px" },
        ...[[result.tracks.length, "vehicles tracked"], [shown.length, "with a readable plate"], [result.frames_sampled, "frames sampled"], [result.department.replace("_", " / ").toUpperCase(), "agency"]]
          .map(([n, l]) => h("div", { class: "kpi" }, h("div", { class: "n", style: typeof n === "string" ? "font-size:26px;padding-top:12px" : "" }, String(n)), h("div", { class: "l" }, l)))),
      h("p", { class: "attrs", style: "margin-top:18px" }, [
        result.source_filename ? `File: ${result.source_filename}` : null,
        result.camera || result.camera_place ? `Camera: ${[result.camera, result.camera_place].filter(Boolean).join(", ")}` : null,
        result.recorded_at ? `Recorded: ${result.recorded_at.replace("T", " ")}` : null,
        result.video ? `${result.video.width}×${result.video.height} at ${result.video.fps} fps${result.video.duration_s ? `, ${result.video.duration_s} s` : ""}` : null,
        result.processing_seconds != null ? `analysed in ${result.processing_seconds} s` : null,
        result.body_model ? `body type: ${result.body_model}` : null,
        result.second_reader_used ? `second reader: ${result.second_reader_used}` : null,
      ].filter(Boolean).join(" · ")),
      h("p", { class: "attrs" }, "Everything about this video is stored on the server: the original, every image, and the data. The ZIP holds all of it."),
      h("p", { class: "hash" }, "Job ", h("span", { class: "mono" }, result.job_id), "  ·  SHA-256 ", h("span", { class: "mono" }, result.source_sha256))),
    ...(advice.summary.length ? [h("section", { class: "panel advice" }, h("h4", {}, "How to get better reads"), advice.summary.map((x) => h("p", { class: "note-l" }, x)),
      h("p", { class: "hint-s" }, "These restate what was measured for each vehicle. A plate that is too small or too blurry stays unknown; it is never guessed."))] : []),
    ...(!result.tracks.length ? [h("section", { class: "panel" }, "No vehicles were tracked in this clip.")]
      : [...(shown.length ? shown.map((t) => trackView(result.job_id, t, acts[t.track_id], flags, result)) : [h("section", { class: "panel" }, "No plate could be read for any vehicle in this clip.")]),
         ...(unread.length ? [unreadView(unread, advice.tracks)] : [])]));
  box.hidden = false;
  history.replaceState(null, "", `?job=${result.job_id}`);
  box.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* ---------- loading jobs, recent list ---------- */
async function openJob(id) {
  setStatus("Loading job…");
  try { await render(await api(`/api/jobs/${encodeURIComponent(id)}`)); setStatus(""); }
  catch (e) { setStatus("Could not open job: " + e.message, true); }
}

async function loadRecent() {
  const box = $("#recent");
  try {
    const m = await api("/api/monitor");
    if (!m.jobs.recent.length) { box.replaceChildren(h("p", { class: "empty" }, "Nothing analysed yet. Upload a clip to start.")); return; }
    box.replaceChildren(...m.jobs.recent.slice(0, 5).map((j) => h("button", { class: "recent-item", type: "button", onclick: () => openJob(j.job_id) },
      h("span", { class: "mono" }, j.job_id), h("span", { class: "muted" }, `${j.filename ? j.filename + " · " : ""}${j.readable} of ${j.tracks} readable`), h("span", { class: "plate-s mono" }, j.best_plate || "no plate"), h("span", { class: "muted" }, when(j.when)))));
  } catch (_) { box.replaceChildren(h("p", { class: "empty" }, "Recent jobs unavailable.")); }
}

/* ---------- upload ---------- */
const fileIn = $("#file"), drop = $("#drop");
function showFile() {
  const fs = [...fileIn.files], f = fs[0], mb = fs.reduce((a, x) => a + x.size, 0) / 1048576;
  $("#drop-title").textContent = fs.length > 1 ? `${fs.length} clips chosen` : f ? f.name : "Drop a clip (or several) here, or click to choose";
  $("#drop-sub").textContent = f ? (fs.length > 1 ? `${mb.toFixed(1)} MB in all. They are analysed one after another.` : `${mb.toFixed(1)} MB, ready to analyse`) : "MP4, AVI, MOV or MKV. About 40 seconds of footage is analysed.";
  $("#go").textContent = fs.length > 1 ? `Analyse ${fs.length} clips` : "Analyse clip";
}
fileIn.addEventListener("change", showFile);
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => { if (e.dataTransfer.files.length) { fileIn.files = e.dataTransfer.files; showFile(); } });

function uploadForm(file) {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("department", $("#department").value);
  [["camera", "#camera"], ["place", "#place"], ["lat", "#lat"], ["lon", "#lon"], ["recorded_at", "#recorded"]].forEach(([k, s]) => { if ($(s).value.trim()) fd.append(k, $(s).value.trim()); });
  return fd;
}
const plateText = (t) => t.match.fused.slots.map((s) => (s.char === "-" ? "" : s.char || "?")).join("");
const QSTATE = { waiting: "waiting", analysing: "analysing…", done: "done", failed: "failed", skipped: "not run" };

/* Several clips at once: one after another, each through the same endpoint a single clip uses. */
async function runBatch(files) {
  const q = $("#queue");
  const rows = files.map((f) => ({ f, state: /\.(mp4|avi|mov|mkv)$/i.test(f.name) ? "waiting" : "skipped", note: /\.(mp4|avi|mov|mkv)$/i.test(f.name) ? "" : "Not a video file." }));
  let stop = false;
  const stopBtn = h("button", { class: "btn sm", type: "button" }, "Stop after this clip");
  stopBtn.addEventListener("click", () => { stop = true; stopBtn.disabled = true; stopBtn.textContent = "Stopping…"; });
  const paint = (running) => q.replaceChildren(h("h4", {}, `Batch: ${rows.filter((r) => r.state === "done").length} of ${rows.length} analysed`),
    h("div", { class: "tablewrap" }, h("table", {}, h("tbody", {}, rows.map((r) => h("tr", {},
      h("td", { style: "max-width:200px;overflow:hidden;text-overflow:ellipsis" }, r.f.name), h("td", {}, h("span", { class: `chip ${r.state === "done" ? "built" : r.state === "failed" ? "rejected" : r.state === "analysing" ? "under_review" : "planned"}` }, QSTATE[r.state])),
      h("td", { class: "mono", style: "font-size:12px" }, r.best || ""), h("td", { style: "white-space:normal;min-width:140px;color:var(--muted);font-size:13px" }, r.note),
      h("td", {}, r.jobId ? h("button", { class: "btn sm", type: "button", onclick: () => openJob(r.jobId) }, "Open") : null)))))),
    running ? h("div", { class: "row-btns" }, stopBtn) : null);
  q.hidden = false; $("#go").disabled = true; paint(true);
  for (const r of rows) {
    if (r.state === "skipped") continue;
    if (stop) { r.state = "skipped"; r.note = "Stopped before this clip."; paint(true); continue; }
    r.state = "analysing"; paint(true);
    try {
      const res = await api((window.EXLEX?.uploadBase || "") + "/api/analyze", { method: "POST", body: uploadForm(r.f) });
      const ok = res.tracks.filter(isReadable);
      r.jobId = res.job_id; r.state = "done"; r.best = ok.length ? plateText(ok[0]) + (ok.length > 1 ? ` +${ok.length - 1}` : "") : "no plate"; r.note = `${ok.length} of ${res.tracks.length} vehicles readable`;
    } catch (e) { r.state = "failed"; r.note = e.message; }
    paint(true);
  }
  paint(false); $("#go").disabled = false; setStatus(""); loadRecent();
}

$("#upload").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const files = [...fileIn.files];
  if (!files.length) return;
  if (files.length > 1) return runBatch(files);
  const file = files[0];
  const fd = uploadForm(file);
  $("#go").disabled = true;
  const t0 = Date.now();
  const tick = setInterval(() => { $("#status").innerHTML = `<span class="spinner"></span>Analysing… ${Math.round((Date.now() - t0) / 1000)} s. Longer clips take a minute or two on CPU.`; $("#status").className = "status-line"; }, 500);
  try { await render(await api((window.EXLEX?.uploadBase || "") + "/api/analyze", { method: "POST", body: fd })); setStatus("Done."); loadRecent(); }
  catch (e) { setStatus("Analysis failed: " + e.message, true); }
  finally { clearInterval(tick); $("#go").disabled = false; }
});
$("#geo").addEventListener("click", () => {
  const s = $("#geo-status");
  if (!navigator.geolocation) { s.textContent = "This device cannot share a location."; s.className = "status-line error"; return; }
  s.textContent = "Asking for your location…"; s.className = "status-line";
  navigator.geolocation.getCurrentPosition((p) => { $("#lat").value = p.coords.latitude.toFixed(5); $("#lon").value = p.coords.longitude.toFixed(5); s.textContent = "Location added."; },
    () => { s.textContent = "Location was not shared. Type it instead."; s.className = "status-line error"; }, { enableHighAccuracy: true, timeout: 10000 });
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
