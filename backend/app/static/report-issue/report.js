"use strict";
const { $, h, api, slotsView, pretty, STATUS_LABEL, when } = UI;
UI.initBar();
UI.initFoot();

const STEPS = ["Photo", "Check the plate", "Details", "Done"];
let state = { draft: null, preview: null, categories: [], geo: null, previewUrl: null };

function setStep(n) {
  $("#stepper").replaceChildren(...STEPS.map((t, i) => h("li", { class: i + 1 < n ? "done" : i + 1 === n ? "now" : "", "aria-current": i + 1 === n ? "step" : null }, h("span", {}, i + 1), t)));
  ["s1", "s2", "s3", "s4"].forEach((id, i) => { $("#" + id).hidden = i + 1 !== n; });
  scrollTo({ top: $("#stepper").offsetTop - 90, behavior: UI.reduceMotion ? "auto" : "smooth" });
}
setStep(1);

const say = (id, msg, err = false) => { const e = $("#" + id); e.className = "status-line" + (err ? " error" : ""); e.textContent = msg; };
const cleanPlate = (t) => t.toUpperCase().replace(/[\s-]/g, "");

/* ---------- step 1: photo ---------- */
async function handleFile(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) return say("s1-status", "That is not an image. Choose a photo.", true);
  if (file.size > 10 * 1024 * 1024) return say("s1-status", "That photo is over 10 MB. Choose a smaller one.", true);
  $("#s1-status").innerHTML = '<span class="spinner"></span>Reading the plate…';
  $("#s1-status").className = "status-line";
  const fd = new FormData();
  fd.append("photo", file);
  try {
    const p = await api("/api/complaints/preview", { method: "POST", body: fd });
    if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
    state = { ...state, draft: p.draft_id, preview: p, previewUrl: URL.createObjectURL(file) };
    $("#preview").src = state.previewUrl;
    $("#read-slots").replaceChildren(slotsView(p.slots));
    $("#read-note").textContent = p.note;
    const crop = $("#crop");
    crop.hidden = !p.plate_crop_url;
    if (p.plate_crop_url) crop.src = p.plate_crop_url;
    $("#use-read").hidden = p.known_count !== 10;
    $("#plate").value = "";
    if (p.exif.observed_at) $("#when").value = p.exif.observed_at;
    if (p.exif.lat != null) state.geo = { lat: p.exif.lat, lon: p.exif.lon, from: "photo" };
    say("s1-status", "");
    setStep(2);
  } catch (e) { say("s1-status", e.message, true); }
}
$("#photo").addEventListener("change", (e) => handleFile(e.target.files[0]));
$("#camera").addEventListener("change", (e) => handleFile(e.target.files[0]));
const drop = $("#drop");
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => handleFile(e.dataTransfer.files[0]));

/* ---------- step 2: check ---------- */
$("#use-read").addEventListener("click", () => { $("#plate").value = state.preview.pattern; });
$("#back1").addEventListener("click", () => setStep(1));
$("#next2").addEventListener("click", () => {
  const p = cleanPlate($("#plate").value);
  if (p && !/^[A-Z0-9]{4,10}$/.test(p)) return say("s2-status", "The plate must be 4 to 10 letters or digits. Leave it empty if you cannot read it.", true);
  say("s2-status", "");
  setStep(3);
});

/* ---------- step 3: details ---------- */
async function loadCategories() {
  state.categories = await api("/api/complaints/categories");
  $("#category").replaceChildren(h("option", { value: "" }, "Choose one…"), ...state.categories.map((c) => h("option", { value: c.id }, c.label)));
}
$("#category").addEventListener("change", () => {
  const c = state.categories.find((x) => x.id === $("#category").value);
  $("#cat-route").textContent = c ? `This goes to: ${c.department_name}.` : "";
});
$("#description").addEventListener("input", () => { $("#desc-count").textContent = $("#description").value.length; });
if (!$("#when").value) { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); $("#when").value = d.toISOString().slice(0, 16); }

$("#geo").addEventListener("click", () => {
  if (!navigator.geolocation) return say("geo-status", "This device cannot share a location.", true);
  say("geo-status", "Asking for your location…");
  navigator.geolocation.getCurrentPosition((pos) => {
    state.geo = { lat: +pos.coords.latitude.toFixed(6), lon: +pos.coords.longitude.toFixed(6), from: "device" };
    if (!$("#location").value) $("#location").value = `Near ${state.geo.lat}, ${state.geo.lon}`;
    say("geo-status", `Location added (${state.geo.lat}, ${state.geo.lon}).`);
  }, () => say("geo-status", "Location was not shared. Type the place instead.", true), { enableHighAccuracy: true, timeout: 10000 });
});
$("#back2").addEventListener("click", () => setStep(2));

$("#details").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const cat = $("#category").value, desc = $("#description").value.trim(), loc = $("#location").value.trim();
  if (!cat) return say("s3-status", "Choose what you are reporting.", true);
  if (desc.length < 5) return say("s3-status", "Describe what you saw (at least a few words).", true);
  if (loc.length < 3) return say("s3-status", "Say where it happened.", true);
  if (!$("#consent").checked) return say("s3-status", "Please tick the box to confirm and agree.", true);
  const when = $("#when").value;
  $("#send").disabled = true;
  say("s3-status", "Sending…");
  try {
    const r = await api("/api/complaints", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ draft_id: state.draft, category: cat, description: desc, location_text: loc,
        lat: state.geo ? state.geo.lat : null, lon: state.geo ? state.geo.lon : null, observed_at: when || null,
        plate_confirmed: cleanPlate($("#plate").value) || null, contact: $("#contact").value.trim() || null, consent: true }),
    });
    $("#done-id").textContent = r.complaint_id;
    $("#done-msg").textContent = `${r.message} It was sent to: ${r.department}.`;
    $("#cid").value = r.complaint_id;
    setStep(4);
    say("s3-status", "");
  } catch (e) { say("s3-status", e.message, true); }
  finally { $("#send").disabled = false; }
});

/* ---------- step 4 + status check ---------- */
$("#again").addEventListener("click", () => {
  state = { ...state, draft: null, preview: null, geo: null };
  ["#photo", "#camera"].forEach((s) => { $(s).value = ""; });
  $("#details").reset();
  $("#cat-route").textContent = "";
  $("#desc-count").textContent = "0";
  setStep(1);
});

$("#status-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const id = $("#cid").value.trim().toLowerCase(), out = $("#status-out");
  if (!id) return;
  try {
    const s = await api(`/api/complaints/${encodeURIComponent(id)}/status`);
    out.replaceChildren(h("span", { class: `chip ${s.status}` }, STATUS_LABEL[s.status]), h("p", { class: "muted", style: "font-size:13.5px;margin-top:10px" }, `${s.category}. Handled by ${s.department}. Filed ${when(s.created_at)}.`));
  } catch (e) { out.replaceChildren(h("p", { class: "err", style: "font-size:13.5px" }, e.status === 404 ? "No report with that ID." : e.message)); }
});

loadCategories().catch((e) => say("s1-status", "Could not load categories: " + e.message, true));
