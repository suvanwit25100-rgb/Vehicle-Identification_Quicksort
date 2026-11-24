"use strict";
const { $, h, api, slotsView, candidateView, banner, pretty, STATUS_LABEL, when } = UI;
UI.initBar();
UI.initFoot();

const AGENCY = { police: "Police", morth_nhai: "MoRTH / NHAI", bsf: "BSF", ssb: "SSB", customs: "Customs" };
let key = sessionStorage.getItem("officerKey") || "";
let selected = null;
const blobs = [];

const call = (path, opts = {}) => api(path, { ...opts, headers: { ...(opts.headers || {}), "X-Officer-Key": key } });
const note = (msg, err = false) => { const s = $("#desk-status"); s.textContent = msg; s.className = "status-line" + (err ? " error" : ""); };

function signedOut(msg) {
  key = "";
  sessionStorage.removeItem("officerKey");
  $("#desk").hidden = true;
  $("#login").hidden = false;
  $("#login-status").textContent = msg || "";
  $("#login-status").className = "status-line" + (msg ? " error" : "");
}

async function imageUrl(path) {
  const r = await fetch(path, { headers: { "X-Officer-Key": key } });
  if (!r.ok) return null;
  const u = URL.createObjectURL(await r.blob());
  blobs.push(u);
  return u;
}

/* ---------- list ---------- */
async function loadList() {
  const q = new URLSearchParams();
  if ($("#f-status").value) q.set("status", $("#f-status").value);
  if ($("#f-dept").value) q.set("department", $("#f-dept").value);
  try {
    const rows = await call("/api/desk/complaints?" + q);
    $("#list").replaceChildren(rows.length ? h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Plate", "Report", "Agency", "Status"].map((t) => h("th", {}, t)))),
      h("tbody", {}, rows.map((r) => h("tr", { class: "click" + (r.id === selected ? " sel" : ""), tabindex: 0, onclick: () => openReport(r.id), onkeydown: (e) => { if (e.key === "Enter") openReport(r.id); } },
        h("td", { class: "mono" }, r.plate_confirmed || r.plate_read, r.plate_confirmed ? h("small", {}, "typed by citizen") : h("small", {}, "system read")),
        h("td", {}, r.category_label.split("(")[0].trim(), h("small", { style: "display:block;color:var(--muted);font-size:11px" }, when(r.created_at))),
        h("td", {}, AGENCY[r.department]), h("td", {}, h("span", { class: `chip ${r.status}` }, STATUS_LABEL[r.status]))))))) : h("p", { class: "empty" }, "No reports match these filters."));
    note(`${rows.length} report${rows.length === 1 ? "" : "s"}`);
  } catch (e) { if (e.status === 401) signedOut("That key was not accepted."); else note(e.message, true); }
}

/* ---------- detail ---------- */
async function openReport(id) {
  selected = id;
  loadList();
  const box = $("#detail");
  box.replaceChildren(h("p", { class: "empty" }, h("span", { class: "spinner" }), "Loading…"));
  blobs.splice(0).forEach(URL.revokeObjectURL);
  try {
    const d = await call(`/api/desk/complaints/${id}`);
    const [photo, crop] = await Promise.all([imageUrl(`/api/desk/complaints/${id}/photo`), d.plate_found ? imageUrl(`/api/desk/complaints/${id}/plate`) : null]);
    const m = d.match;
    const map = d.lat != null ? h("a", { href: `https://www.openstreetmap.org/?mlat=${d.lat}&mlon=${d.lon}#map=17/${d.lat}/${d.lon}`, target: "_blank", rel: "noopener noreferrer" }, "open on a map ↗") : null;
    const sel = h("select", { id: "d-status", "aria-label": "Status" }, d.statuses.map((s) => h("option", { value: s, selected: s === d.status }, STATUS_LABEL[s])));
    const noteEl = h("textarea", { id: "d-note", maxlength: 1000, placeholder: "Note for the file (seen by officers only)" }, d.officer_note || "");
    const msg = h("span", { class: "status-line", id: "d-msg", role: "status", "aria-live": "polite" });
    box.replaceChildren(
      h("div", { class: "d-head" }, h("h3", { style: "margin:0" }, `Report ${d.id}`), h("span", { class: `chip ${d.status}` }, STATUS_LABEL[d.status])),
      h("p", { class: "muted", style: "font-size:13.5px;margin:6px 0 18px" }, `${d.category_label} · ${d.department_name} · filed ${when(d.created_at)}`),
      h("div", { class: "d-imgs" }, photo ? h("img", { src: photo, alt: "Citizen photo", class: "preview" }) : h("p", { class: "empty" }, "Photo unavailable."), crop ? h("img", { src: crop, alt: "Plate crop", class: "crop-img" }) : null),
      h("h4", {}, "System read of the photo"), slotsView(d.read_slots),
      d.plate_confirmed ? h("p", { class: "typed" }, "Citizen typed: ", h("span", { class: "mono" }, d.plate_confirmed)) : h("p", { class: "typed muted" }, "The citizen did not type a plate."),
      h("h4", { style: "margin-top:24px" }, "Registry match"), h("p", { class: "muted", style: "font-size:13px;margin-bottom:10px" }, `Basis: ${d.match_basis}.`),
      banner(m), m.candidates.map((c, i) => candidateView(c, i + 1)),
      h("h4", { style: "margin-top:24px" }, "Report details"),
      h("dl", { class: "dl" }, h("dt", {}, "Description"), h("dd", {}, d.description), h("dt", {}, "Location"), h("dd", {}, d.location_text, d.lat != null ? ` (${d.lat}, ${d.lon}) ` : "", map),
        h("dt", {}, "Observed"), h("dd", {}, d.observed_at ? when(d.observed_at) : "not given"), h("dt", {}, "Contact"), h("dd", {}, d.contact || "none given"),
        h("dt", {}, "Photo SHA-256"), h("dd", { class: "mono", style: "word-break:break-all;font-size:12px" }, d.image_sha256)),
      h("h4", { style: "margin-top:24px" }, "Triage"),
      h("div", { class: "triage" }, sel, noteEl, h("div", { class: "row-btns" }, h("button", { class: "btn primary sm", type: "button", onclick: async () => {
        msg.textContent = "Saving…";
        try { await call(`/api/desk/complaints/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: sel.value, note: noteEl.value }) }); msg.textContent = "Saved."; loadList(); openReport(id); }
        catch (e) { msg.textContent = e.message; msg.className = "status-line error"; }
      } }, "Save"), msg)));
    if (innerWidth < 1000) box.scrollIntoView({ behavior: "smooth" });
  } catch (e) { if (e.status === 401) signedOut("That key was not accepted."); else box.replaceChildren(h("p", { class: "err" }, e.message)); }
}

/* ---------- sign-in ---------- */
function enter() {
  $("#login").hidden = true;
  $("#desk").hidden = false;
  $("#f-status").replaceChildren(h("option", { value: "" }, "All statuses"), ...Object.keys(STATUS_LABEL).filter((s) => ["new", "under_review", "verified", "forwarded", "closed", "rejected"].includes(s)).map((s) => h("option", { value: s }, STATUS_LABEL[s])));
  $("#f-dept").replaceChildren(h("option", { value: "" }, "All agencies"), ...Object.entries(AGENCY).map(([k, v]) => h("option", { value: k }, v)));
  loadList();
  loadWatch();
}
$("#login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  key = $("#key").value.trim();
  if (!key) return;
  try { await call("/api/desk/complaints"); sessionStorage.setItem("officerKey", key); $("#key").value = ""; enter(); }
  catch (e) { signedOut(e.status === 401 ? "That key was not accepted." : e.message); }
});
$("#signout").addEventListener("click", () => signedOut("Signed out."));
$("#refresh").addEventListener("click", loadList);
$("#f-status").addEventListener("change", loadList);
$("#f-dept").addEventListener("change", loadList);
if (key) { call("/api/desk/complaints").then(enter).catch(() => signedOut()); }

/* ---------- watch-list ---------- */
const wnote = (msg, err = false) => { const e = $("#watch-status"); e.textContent = msg; e.className = "status-line" + (err ? " error" : ""); };
async function loadWatch() {
  try {
    const d = await call("/api/desk/watchlist");
    $("#watch-list").replaceChildren(d.entries.length ? h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Plate", "Reason", "Listed", ""].map((t) => h("th", {}, t)))),
      h("tbody", {}, d.entries.map((e) => h("tr", {}, h("td", { class: "mono" }, e.plate), h("td", {}, e.reason), h("td", {}, when(e.created_at)),
        h("td", {}, h("button", { class: "btn sm", type: "button", onclick: async () => { try { await call(`/api/desk/watchlist/${e.id}`, { method: "DELETE" }); loadWatch(); } catch (x) { wnote(x.message, true); } } }, "Remove"))))))) : h("p", { class: "empty" }, "Nothing on the watch-list."));
    $("#watch-alerts").replaceChildren(d.alerts.length ? h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Hit", "Listed plate", "Read as", "Video", "Reason"].map((t) => h("th", {}, t)))),
      h("tbody", {}, d.alerts.map((a) => h("tr", {}, h("td", {}, h("span", { class: "chip " + (a.level === "exact" ? "verified" : "under_review") }, a.level)), h("td", { class: "mono" }, a.watch_plate), h("td", { class: "mono" }, a.read),
        h("td", {}, h("a", { href: `/console/?job=${a.job_id}` }, `${a.filename || a.job_id} #${a.track_id}`)), h("td", {}, a.reason)))))) : h("p", { class: "empty" }, d.entries.length ? "No stored video contains a plate that fits the list." : "Add a plate to start watching."));
  } catch (e) { if (e.status === 401) signedOut("That key was not accepted."); else wnote(e.message, true); }
}
$("#watch-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    await call("/api/desk/watchlist", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plate: $("#w-plate").value, reason: $("#w-reason").value }) });
    $("#w-plate").value = ""; $("#w-reason").value = ""; wnote("Added."); loadWatch();
  } catch (e) { wnote(e.message, true); }
});
