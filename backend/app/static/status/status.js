"use strict";
const { $, h, api, when } = UI;
UI.initBar();
UI.initFoot();

const say = (m, err = false) => { $("#msg").textContent = m; $("#msg").className = "status-line" + (err ? " error" : ""); };

async function show(id) {
  const out = $("#out");
  out.hidden = true;
  try {
    const p = await api(`/api/complaints/${encodeURIComponent(id)}/progress`);
    say("");
    const at = p.steps.findIndex((s) => s.id === p.status);
    out.replaceChildren(
      h("div", { class: "st-head" }, h("span", { class: "mono" }, p.complaint_id), h("span", { class: `chip ${p.status}` }, p.label)),
      h("p", { class: "st-meaning" }, p.meaning),
      p.rejected ? null : h("ol", { class: "st-steps", "aria-label": "Progress" }, p.steps.map((s, i) => h("li", { class: i < at ? "done" : i === at ? "now" : "", "aria-current": i === at ? "step" : null }, h("span", {}, i + 1), s.label))),
      h("dl", { class: "dl" }, h("dt", {}, "About"), h("dd", {}, p.category), h("dt", {}, "Handled by"), h("dd", {}, p.department), h("dt", {}, "Filed"), h("dd", {}, when(p.filed_at)), h("dt", {}, "Last change"), h("dd", {}, when(p.updated_at))),
      h("h4", { style: "margin-top:22px" }, "What has happened"),
      h("ul", { class: "st-timeline" }, p.timeline.map((e) => h("li", {}, h("small", {}, when(e.at)), e.text))),
      h("p", { class: "hint-s" }, p.note));
    out.hidden = false;
    history.replaceState(null, "", `?id=${p.complaint_id}`);
  } catch (e) { say(e.status === 404 ? "No report with that ID. Check it for a typing mistake." : e.status === 429 ? e.message : "Could not look that up: " + e.message, true); }
}
$("#f").addEventListener("submit", (ev) => { ev.preventDefault(); const id = $("#cid").value.trim().toLowerCase(); if (id) show(id); });
const preset = new URLSearchParams(location.search).get("id");
if (preset) { $("#cid").value = preset; show(preset.toLowerCase()); }
