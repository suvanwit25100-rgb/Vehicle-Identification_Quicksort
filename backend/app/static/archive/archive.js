"use strict";
const { $, h, api, when } = UI;
UI.initBar();
UI.initFoot();

const AGENCY = { police: "Police", morth_nhai: "MoRTH / NHAI", bsf: "BSF", ssb: "SSB", customs: "Customs" };
const size = (b) => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${b ? Math.max(1, Math.round(b / 1024)) : 0} KB`);

function render(rows, query) {
  const bytes = rows.reduce((a, r) => a + r.size_bytes, 0);
  $("#totals").replaceChildren(
    h("span", {}, h("b", {}, String(rows.length)), query ? `video${rows.length === 1 ? "" : "s"} with a plate like “${query.toUpperCase()}”` : `analys${rows.length === 1 ? "is" : "es"} stored`),
    h("span", {}, h("b", {}, size(bytes)), "on the server"),
    h("span", {}, h("b", {}, String(rows.filter((r) => r.has_video).length)), "with the original video kept"));
  if (!rows.length) {
    $("#list").replaceChildren(h("p", { class: "empty" }, query ? "No stored video contains a plate that fits that. Unknown characters (?) in either plate match anything, so this is a real absence, not a misread." : "Nothing stored yet. Analyse a clip in the console and it will appear here."));
    return;
  }
  $("#list").replaceChildren(h("div", { class: "tablewrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ["When", "File", "Agency", "Vehicles", "Plates read", "Video", "Size", ""].map((t) => h("th", {}, t)))),
    h("tbody", {}, rows.map((j) => h("tr", {},
      h("td", {}, when(j.when)),
      h("td", { style: "max-width:220px;overflow:hidden;text-overflow:ellipsis" }, j.filename || h("span", { class: "muted" }, "(name not recorded)"), h("small", { class: "mono", style: "display:block;color:var(--dim);font-size:11px" }, j.job_id)),
      h("td", {}, AGENCY[j.department] || j.department),
      h("td", { class: "mono" }, `${j.readable} of ${j.vehicles}`),
      h("td", {}, j.plates.length ? h("div", { class: "platechips" }, j.plates.map((p) => h("span", { class: j.matched_plates.includes(p) ? "hit" : "" }, p))) : h("span", { class: "muted" }, "none readable")),
      h("td", { class: "mono", style: "font-size:12px" }, j.video ? `${j.video.width}×${j.video.height}${j.video.duration_s ? ` · ${j.video.duration_s}s` : ""}` : "·"),
      h("td", { class: "mono", style: "font-size:12px" }, size(j.size_bytes)),
      h("td", {}, h("div", { class: "actions" },
        h("a", { class: "btn sm", href: `/console/?job=${j.job_id}` }, "Open"),
        h("a", { class: "btn sm", href: `/api/jobs/${j.job_id}/report`, target: "_blank", rel: "noopener" }, "Report"),
        h("a", { class: "btn primary sm", href: `/api/jobs/${j.job_id}/download`, download: `case-${j.job_id}.zip` }, "ZIP")))))))));
}

let timer, seq = 0;
async function load() {
  const q = $("#q").value.trim(), mine = ++seq;
  try {
    const rows = await api("/api/jobs" + (q ? `?plate=${encodeURIComponent(q)}` : ""));
    if (mine === seq) render(rows, q);       // ignore a slow answer to an older search
  } catch (e) { $("#list").replaceChildren(h("p", { class: "err" }, "Could not load the archive: " + e.message)); }
}
$("#q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 280); });
$("#clear").addEventListener("click", () => { $("#q").value = ""; load(); });
const preset = new URLSearchParams(location.search).get("plate");
if (preset) $("#q").value = preset;
load();
