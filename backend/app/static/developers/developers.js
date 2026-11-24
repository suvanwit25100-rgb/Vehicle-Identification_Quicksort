"use strict";
const { $, h, api } = UI;
UI.initBar();
UI.initFoot();

const GROUPS = [["/api/analyze", "Analyse a video"], ["/api/jobs", "Stored analyses"], ["/api/sightings", "Repeat sightings"], ["/api/match", "Plate matching"], ["/api/complaints", "Citizen reports"],
  ["/api/desk", "Officer: reports, watch-list, map"], ["/api/officer", "Officer: accounts, audit, retention"], ["/api/monitor", "Monitor"], ["/api/calibration", "Monitor"],
  ["/api/departments", "Agencies and registry"], ["/api/registry", "Agencies and registry"], ["/api/brains", "Models"], ["/api/health", "Health"]];
const groupOf = (p) => (GROUPS.find(([pre]) => p.startsWith(pre)) || [0, "Other"])[1];
const isOfficer = (p) => p.startsWith("/api/desk") || p.startsWith("/api/officer");
const origin = location.origin;

const EXAMPLES = [
  ["Analyse a video", `curl -F "file=@clip.mp4" -F "department=police" ${origin}/api/analyze`],
  ["Find a plate in stored videos", `curl "${origin}/api/jobs?plate=UP14CA0914"`],
  ["Plates seen in 2+ videos", `curl "${origin}/api/sightings"`],
  ["Download a case file", `curl -OJ ${origin}/api/jobs/<job_id>/download`],
  ["Sign in as an officer", `curl -X POST ${origin}/api/officer/login -H "Content-Type: application/json" -d '{"username":"…","password":"…"}'`],
  ["List reports (officer)", `curl ${origin}/api/desk/complaints -H "Authorization: Bearer <token>"`],
];
$("#examples").replaceChildren(...EXAMPLES.map(([t, c]) => h("div", { class: "ex" }, h("b", {}, t), h("pre", {}, h("code", {}, c)))));

let spec = null;
function render() {
  const q = $("#q").value.trim().toLowerCase();
  const rows = [];
  for (const [path, ops] of Object.entries(spec.paths)) for (const [method, op] of Object.entries(ops)) {
    if (!["get", "post", "put", "patch", "delete"].includes(method)) continue;
    const text = (op.description || op.summary || "").split("\n")[0].trim();
    rows.push({ path, method: method.toUpperCase(), text, group: groupOf(path), officer: isOfficer(path) });
  }
  const shown = rows.filter((r) => !q || `${r.path} ${r.method} ${r.text} ${r.group}`.toLowerCase().includes(q));
  $("#totals").replaceChildren(h("span", {}, h("b", {}, String(shown.length)), shown.length === rows.length ? "endpoints" : `of ${rows.length} endpoints`));
  const byGroup = new Map();
  shown.forEach((r) => byGroup.set(r.group, [...(byGroup.get(r.group) || []), r]));
  $("#list").replaceChildren(...(byGroup.size ? [...byGroup].map(([g, rs]) => h("div", { class: "grp" }, h("h4", {}, g),
    h("div", { class: "tablewrap" }, h("table", {}, h("tbody", {}, rs.map((r) => h("tr", {}, h("td", {}, h("span", { class: `verb ${r.method}` }, r.method)), h("td", { class: "mono ep" }, r.path),
      h("td", {}, r.officer ? h("span", { class: "chip partial" }, "officer") : null), h("td", { style: "white-space:normal;min-width:220px;color:var(--muted)" }, r.text))))))))
    : [h("p", { class: "empty" }, "No endpoint matches that.")]));
}
api("/openapi.json").then((s) => { spec = s; render(); }).catch((e) => $("#list").replaceChildren(h("p", { class: "err" }, "Could not load the API description: " + e.message)));
let t; $("#q").addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => spec && render(), 200); });
