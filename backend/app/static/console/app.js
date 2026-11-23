"use strict";

const $ = (id) => document.getElementById(id);
const STATUS_LABEL = {
  match: "Match",
  ambiguous: "Ambiguous, verify manually",
  no_confident_match: "No confident match",
  insufficient_evidence: "Insufficient evidence",
};

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function topOf(dist) {
  if (!dist || !Object.keys(dist).length) return "unknown";
  const k = Object.keys(dist).sort((a, b) => dist[b] - dist[a])[0];
  return `${k.replace("_", " ")} (${dist[k].toFixed(2)})`;
}

function setStatus(msg, isError = false) {
  const s = $("status");
  s.textContent = msg;
  s.className = "status" + (isError ? " error" : "");
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch (_) {}
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return r.json();
}

function slotsView(fused) {
  return h("div", { class: "slots", role: "list", "aria-label": "Recovered plate characters" },
    fused.slots.map((s) =>
      h("div", { class: "slot" + (s.char ? "" : " unk"), role: "listitem",
                 title: s.char ? `Read as ${s.char}` : "Unreadable, not guessed" },
        h("b", {}, s.char || "?"), h("small", {}, s.confidence.toFixed(2)))));
}

function plateView(cand) {
  const el = h("span", { class: "plate" });
  [...cand.plate].forEach((ch, i) => {
    const cls = cand.mismatched_slots.includes(i) ? "miss" : cand.unknown_slots.includes(i) ? "unkc" : "";
    el.append(h("span", { class: cls }, ch));
  });
  return el;
}

function candidateView(c, rank) {
  return h("div", { class: "cand" },
    h("div", { class: "cand-h" },
      h("span", { class: "rank" }, `#${rank}`),
      plateView(c),
      c.flags.map((f) => h("span", { class: "flag" }, f.replace("_", " "))),
      h("span", { class: "bar", role: "img", "aria-label": `confidence ${c.confidence.toFixed(2)}` },
        h("i", { style: `width:${Math.round(c.confidence * 100)}%` })),
      h("span", { class: "score" }, c.confidence.toFixed(2))),
    h("div", { class: "sub" }, `${c.make} ${c.model}, ${c.colour}, ${c.body_type.replace("_", " ")} (registry ${c.reg_id})`),
    h("ul", {}, c.reasons.map((r) => h("li", {}, r))));
}

function framesTable(reads) {
  if (!reads.length) return h("p", { class: "hint" }, "No plate was located in any frame.");
  const head = h("tr", {}, h("th", {}, "Frame"), h("th", {}, "Sharp"),
    Array.from({ length: 10 }, (_, i) => h("th", {}, i + 1)));
  const rows = reads.map((fr) => h("tr", {},
    h("td", { class: "f" }, fr.frame_id), h("td", {}, Math.round(fr.sharpness)),
    fr.chars.map((c) => c
      ? h("td", { class: "mono" }, c.char, h("small", {}, c.conf.toFixed(2)))
      : h("td", { class: "hint" }, "-"))));
  return h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, head), h("tbody", {}, rows)));
}

function trackView(jobId, t) {
  const m = t.match;
  return h("article", { class: "track" },
    h("div", { class: "track-h" },
      h("h2", {}, `Vehicle track ${t.track_id} (${t.vehicle_label})`),
      h("span", { class: "sub" }, `seen in ${t.frames_seen} frames, plate in ${t.frames_with_plate}`)),
    h("p", { class: "sub" }, `Colour: ${topOf(t.colour)}. Body type: ${topOf(t.body_type)}.` +
      (t.max_plate_width_px ? ` Largest plate seen: ${t.max_plate_width_px} px wide.` : "") +
      ((t.merged_from || []).length ? ` Merged with track${t.merged_from.length > 1 ? "s" : ""} ${t.merged_from.join(", ")}: the plates agree on 6+ characters and clash on none.` : "")),
    h("div", { class: `banner ${m.status}` }, h("b", {}, STATUS_LABEL[m.status] + "."), m.message),
    h("h3", {}, "Recovered plate"),
    slotsView(m.fused),
    h("p", { class: "hint" }, "Amber ? positions were unreadable across frames and are reported as unknown."),
    t.plate_crops.length ? h("h3", {}, "Sharpest plate crops") : null,
    t.plate_crops.length ? h("div", { class: "crops" }, t.plate_crops.map((n) =>
      h("img", { src: `/api/jobs/${jobId}/crops/${n}`, alt: `Plate crop ${n}` }))) : null,
    m.candidates.length ? h("h3", {}, "Ranked candidates") : null,
    m.candidates.map((c, i) => candidateView(c, i + 1)),
    h("h3", {}, "Characters read per frame"),
    framesTable(t.frame_reads));
}

const isReadable = (t) => t.match.fused.slots.some((s) => s.char);

function unreadView(tracks) {
  const rows = tracks.map((t) => h("tr", {},
    h("td", {}, t.track_id), h("td", { class: "f" }, t.vehicle_label), h("td", {}, t.frames_seen),
    h("td", { class: "f wrap" }, t.plate_note || "No readable plate characters.")));
  return h("details", { class: "panel unread" },
    h("summary", {}, `${tracks.length} vehicle${tracks.length === 1 ? "" : "s"} without a readable plate`),
    h("div", { class: "tablewrap" }, h("table", {},
      h("thead", {}, h("tr", {}, h("th", {}, "Track"), h("th", {}, "Vehicle"), h("th", {}, "Frames seen"),
        h("th", {}, "Why no plate was read"))),
      h("tbody", {}, rows))));
}

function render(result) {
  const box = $("results");
  const shown = result.tracks.filter(isReadable);
  const unread = result.tracks.filter((t) => !isReadable(t));
  box.replaceChildren(
    h("section", { class: "panel" },
      h("h2", {}, "Analysis result"),
      h("p", { class: "meta" },
        h("span", {}, "Job ", h("span", { class: "mono" }, result.job_id)),
        h("span", {}, `Department: ${result.department}`),
        h("span", {}, `${result.frames_sampled} frames sampled`),
        h("span", {}, `${result.tracks.length} vehicle track(s)`),
        h("span", {}, `${shown.length} with a readable plate`)),
      h("div", { class: "hash" }, "SHA-256 ", result.source_sha256),
      h("p", { class: "actions" },
        h("a", { href: `/api/jobs/${result.job_id}/report`, target: "_blank", rel: "noopener" }, "Open printable report"))),
    ...(!result.tracks.length
      ? [h("section", { class: "panel" }, "No vehicles were tracked in this clip.")]
      : [
          ...(shown.length
            ? shown.map((t) => trackView(result.job_id, t))
            : [h("section", { class: "panel" }, "No plate could be read for any vehicle in this clip.")]),
          ...(unread.length ? [unreadView(unread)] : []),
        ]));
  box.hidden = false;
  box.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function init() {
  try {
    const depts = await api("/api/departments");
    $("department").replaceChildren(...depts.map((d) => h("option", { value: d.id }, d.name)));
  } catch (e) { setStatus("Could not load departments: " + e.message, true); }
  try {
    const brains = await api("/api/brains");
    $("brains").replaceChildren(...brains.map((b) =>
      h("span", { class: "chip " + (b.ready ? "ready" : "missing"), title: `${b.role} - ${b.source}` },
        `${b.id.replace("_", " ")}: ${b.ready ? "ready" : "not installed"}`)));
  } catch (_) {}
}

$("upload").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const file = $("file").files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  fd.append("department", $("department").value);
  $("go").disabled = true;
  setStatus("Analysing clip. This can take a minute for longer footage...");
  try {
    render(await api("/api/analyze", { method: "POST", body: fd }));
    setStatus("Done.");
  } catch (e) { setStatus("Analysis failed: " + e.message, true); }
  finally { $("go").disabled = false; }
});

$("lookup").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const id = $("jobid").value.trim();
  if (!id) return;
  setStatus("Loading job...");
  try { render(await api(`/api/jobs/${encodeURIComponent(id)}`)); setStatus(""); }
  catch (e) { setStatus("Could not open job: " + e.message, true); }
});

init();
