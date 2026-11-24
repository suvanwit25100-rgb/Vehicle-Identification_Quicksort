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
        h("a", { class: "btn sm", href: `/api/jobs/${j.job_id}/report.pdf`, target: "_blank", rel: "noopener" }, "PDF"),
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

async function loadRepeats() {
  const box = $("#repeats");
  try {
    const groups = await api("/api/sightings");
    box.replaceChildren(...(groups.length ? groups.map((g) => h("div", { class: "repeat" },
      h("div", { class: "repeat-head" }, h("span", { class: "mono repeat-plate" }, g.plate), h("span", { class: "chip" + (g.complete ? "" : " partial") }, g.complete ? "whole plate" : "partly read"),
        h("span", { class: "muted", style: "font-size:13px" }, `${g.footage_count} videos · first ${when(g.first_seen)} · last ${when(g.last_seen)}`)),
      h("div", { class: "platechips" }, g.sightings.map((x) => h("a", { class: "hit", href: `/console/?job=${x.job_id}`, title: `${x.filename || x.job_id}, vehicle ${x.track_id}` }, `${x.filename || x.job_id} #${x.track_id}`))))) :
      [h("p", { class: "empty" }, "No plate has appeared in more than one video yet. Repeat sightings show up here once the same vehicle is read in a second, different video.")]));
  } catch (e) { box.replaceChildren(h("p", { class: "err" }, "Could not load sightings: " + e.message)); }
}
loadRepeats();

/* ---------- follow a plate across cameras ---------- */
let leafletReady;
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  leafletReady ??= new Promise((ok, fail) => {
    document.head.append(h("link", { rel: "stylesheet", href: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css" }));
    const js = h("script", { src: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js" });
    js.onload = ok; js.onerror = () => fail(new Error("The map could not be loaded (offline?)."));
    document.head.append(js);
  });
  return leafletReady;
}
$("#trail-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const q = $("#trail-q").value.trim(), out = $("#trail-out");
  if (!q) return;
  out.replaceChildren(h("p", { class: "empty" }, h("span", { class: "spinner" }), "Looking…"));
  try {
    const groups = await api(`/api/trail?plate=${encodeURIComponent(q)}`);
    if (!groups.length) return out.replaceChildren(h("p", { class: "empty" }, "No stored video has a plate that fits that. Unknown characters (?) match anything, so this is a real absence, not a misread."));
    out.replaceChildren(...groups.map((g) => trailView(g)));
  } catch (e) { out.replaceChildren(h("p", { class: "err" }, e.status === 422 ? "Type at least 4 known characters." : e.message)); }
});
function trailView(g) {
  const withPos = g.stops.filter((s) => s.lat != null && s.lon != null);
  const map = withPos.length ? h("div", { class: "map", role: "img", "aria-label": `Map of where ${g.plate} was seen` }) : null;
  const box = h("div", { class: "trail" },
    h("div", { class: "repeat-head" }, h("span", { class: "mono repeat-plate" }, g.plate), h("span", { class: "chip" + (g.complete ? "" : " partial") }, g.complete ? "whole plate" : "partly read"),
      h("span", { class: "muted", style: "font-size:13px" }, `${g.stops.length} sighting${g.stops.length === 1 ? "" : "s"} in ${g.footage_count} video${g.footage_count === 1 ? "" : "s"} · ordered by ${g.ordered_by}`)),
    map,
    h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["#", "When", "Camera", "Place", "Video", ""].map((t) => h("th", {}, t)))),
      h("tbody", {}, g.stops.map((s, i) => h("tr", {}, h("td", { class: "mono" }, String(i + 1)), h("td", {}, s.recorded_at ? when(s.recorded_at) : h("span", { class: "muted" }, `${when(s.when)} (analysed)`)),
        h("td", {}, s.camera || h("span", { class: "muted" }, "not given")), h("td", {}, s.place || (s.lat != null ? `${s.lat.toFixed(4)}, ${s.lon.toFixed(4)}` : h("span", { class: "muted" }, "not given"))),
        h("td", {}, s.filename || s.job_id), h("td", {}, h("a", { class: "btn sm", href: `/console/?job=${s.job_id}` }, "Open"))))))),
    withPos.length < g.stops.length ? h("p", { class: "hint-s" }, `${g.stops.length - withPos.length} sighting${g.stops.length - withPos.length === 1 ? " has" : "s have"} no location, so ${g.stops.length - withPos.length === 1 ? "it is" : "they are"} not on the map.`) : null);
  if (map) setTimeout(async () => {
    try { await loadLeaflet(); } catch (e) { map.replaceChildren(h("p", { class: "err" }, e.message + " The table still lists every stop.")); return; }
    const m = L.map(map, { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap contributors" }).addTo(m);
    const pts = withPos.map((s) => [s.lat, s.lon]);
    if (pts.length > 1) L.polyline(pts, { color: "#ff2a3f", weight: 3, opacity: .7, dashArray: "6 8" }).addTo(m);
    withPos.forEach((s, i) => L.marker ? L.circleMarker([s.lat, s.lon], { radius: 11, color: "#fff", weight: 2, fillColor: "#ff2a3f", fillOpacity: .95 })
      .bindTooltip(String(g.stops.indexOf(s) + 1), { permanent: true, direction: "center", className: "trail-n" })
      .bindPopup(h("div", {}, h("b", {}, s.camera || "Camera"), h("br"), s.place || "", s.place ? h("br") : null, s.recorded_at ? when(s.recorded_at) : when(s.when) + " (analysed)")).addTo(m) : null);
    m.fitBounds(L.latLngBounds(pts).pad(0.3), { maxZoom: 16 });
  }, 0);
  return box;
}
