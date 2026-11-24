"use strict";
const { $, h, api, slotsView, candidateView, banner, pretty, STATUS_LABEL, when } = UI;
UI.initBar();
UI.initFoot();

/* Optional pieces are written as `cond ? node : null`; the native replaceChildren would print "null", so skip empty children here. */
const nativeReplace = Element.prototype.replaceChildren;
Element.prototype.replaceChildren = function (...kids) { return nativeReplace.apply(this, kids.flat(Infinity).filter((k) => k != null && k !== false)); };

const AGENCY = { police: "Police", morth_nhai: "MoRTH / NHAI", bsf: "BSF", ssb: "SSB", customs: "Customs" };
const STATES = ["new", "under_review", "verified", "forwarded", "closed", "rejected"];
const store = {
  get(k) { try { return sessionStorage.getItem(k) || ""; } catch (e) { return ""; } },
  set(k, v) { try { v ? sessionStorage.setItem(k, v) : sessionStorage.removeItem(k); } catch (e) { /* storage blocked: the session lasts until reload */ } },
};
let token = store.get("officerToken");
let me = null;
let team = [];
let dash = null;
let blobs = [];

const call = (path, opts = {}) => api(path, { ...opts, headers: { ...(opts.headers || {}), Authorization: `Bearer ${token}` } });
const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
async function blobUrl(path) {
  const r = await fetch(path, { headers: { Authorization: `Bearer ${token}` } });
  if (!r.ok) return null;
  const u = URL.createObjectURL(await r.blob());
  blobs.push(u);
  return u;
}
async function download(path, filename) {
  const u = await blobUrl(path);
  if (!u) throw new Error("Download failed.");
  const a = h("a", { href: u, download: filename });
  document.body.append(a); a.click(); a.remove();
}
const say = (el, msg, err = false) => { el.textContent = msg; el.className = "status-line" + (err ? " error" : ""); };
const chip = (s) => h("span", { class: `chip ${s}` }, STATUS_LABEL[s] || pretty(s));
const field = (label, input) => h("label", { class: "f" }, label, input);
const head = (title, sub, ...tools) => h("div", { class: "op-head" }, h("div", {}, h("h2", {}, title), sub ? h("p", {}, sub) : null), tools.length ? h("div", { class: "act-row" }, tools) : null);
const table = (cols, rows, empty) => rows.length ? h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, cols.map((c) => h("th", {}, c)))), h("tbody", {}, rows))) : h("p", { class: "empty" }, empty);

/* ---------- sign in / out ---------- */
function showLogin(msg) {
  token = ""; me = null; store.set("officerToken", "");
  $("#op").hidden = true; $("#login").hidden = false;
  say($("#login-status"), msg || "", !!msg);
}
async function enter(info) {
  me = info;
  $("#login").hidden = true; $("#op").hidden = false;
  $("#who-name").textContent = me.name;
  $("#who-role").textContent = me.role === "admin" ? (me.id === "key" ? "Administrator · master key" : "Administrator") : "Officer";
  try { team = await call("/api/officer/team"); } catch (e) { team = []; }
  route();
}
let mode = "user";
$("#login-tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-mode]");
  if (!b) return;
  mode = b.dataset.mode;
  [...$("#login-tabs").children].forEach((x) => x.setAttribute("aria-selected", String(x === b)));
  $("#f-user").hidden = mode !== "user"; $("#f-key").hidden = mode !== "key";
});
$("#login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const body = mode === "key" ? { key: $("#key").value.trim() } : { username: $("#username").value.trim(), password: $("#password").value };
  if (mode === "key" ? !body.key : !(body.username && body.password)) return say($("#login-status"), mode === "key" ? "Enter the master key." : "Enter your username and password.", true);
  say($("#login-status"), "Signing in…");
  try {
    const r = await api("/api/officer/login", json("POST", body));
    token = r.token; store.set("officerToken", token);
    $("#key").value = ""; $("#password").value = "";
    say($("#login-status"), "");
    await enter(r.officer);
  } catch (e) { say($("#login-status"), e.message, true); }
});
$("#signout").addEventListener("click", async () => { try { await call("/api/officer/logout", { method: "POST" }); } catch (e) { /* already gone */ } showLogin("Signed out."); });

/* ---------- router ---------- */
const ROUTES = {
  dashboard: ["Dashboard", viewDashboard], reports: ["Reports", viewReports], analyses: ["Analyses", viewAnalyses], watchlist: ["Watch-list", viewWatchlist],
  sightings: ["Repeat sightings", viewSightings], audit: ["Audit trail", viewAudit, true], team: ["Team", viewTeam, true], account: ["My account", viewAccount],
};
function route() {
  if (!me) return;
  const [name, arg] = (location.hash.replace(/^#\/?/, "") || "dashboard").split("/");
  const key = ROUTES[name] && !(ROUTES[name][2] && me.role !== "admin") ? name : "dashboard";
  blobs.splice(0).forEach(URL.revokeObjectURL);
  $("#op-nav").replaceChildren(...Object.entries(ROUTES).filter(([, r]) => !r[2] || me.role === "admin").map(([k, r]) =>
    h("a", { href: `#/${k}`, "aria-current": k === key ? "page" : null }, r[0], badge(k))));
  const view = $("#view");
  view.replaceChildren(h("p", { class: "empty" }, h("span", { class: "spinner" }), "Loading…"));
  ROUTES[key][1](view, arg).catch((e) => { if (e.status === 401) showLogin("Your session ended. Sign in again."); else view.replaceChildren(h("p", { class: "err" }, e.message)); });
  refreshBadges();
}
function badge(k) {
  const n = dash && (k === "reports" ? dash.reports.unassigned_open : k === "watchlist" ? dash.watchlist.hits_exact : 0);
  return n ? h("span", { class: "count", title: k === "reports" ? "open and unassigned" : "exact hits" }, String(n)) : null;
}
async function refreshBadges() {
  try { dash = await call("/api/officer/dashboard"); } catch (e) { return; }
  document.querySelectorAll("#op-nav a").forEach((a) => {
    const k = a.getAttribute("href").slice(2);
    a.querySelector(".count")?.remove();
    const b = badge(k); if (b) a.append(b);
  });
}
addEventListener("hashchange", route);

/* ---------- dashboard ---------- */
async function viewDashboard(view) {
  const d = await call("/api/officer/dashboard");
  dash = d;
  const r = d.reports, max = Math.max(1, ...r.per_day.map((x) => x.count));
  const kpi = (n, l, href, cls = "") => h(href ? "a" : "div", { class: `kpi ${cls}`, href }, h("div", { class: "n" }, String(n)), h("div", { class: "l" }, l));
  const brk = (obj, label) => { const entries = Object.entries(obj).sort((a, b) => b[1] - a[1]); const top = Math.max(1, ...entries.map((e) => e[1]));
    return entries.length ? h("div", { class: "brk" }, entries.map(([k, n]) => h("div", { class: "row" }, h("span", {}, label(k)), h("span", { class: "track" }, h("i", { style: `width:${(n / top) * 100}%` })), h("span", { class: "mono-s" }, n)))) : h("p", { class: "empty" }, "Nothing yet."); };
  view.replaceChildren(
    head(`Good to see you, ${me.name.split(" ")[0]}.`, "What needs attention right now, from the stored data. Nothing here is estimated."),
    h("div", { class: "kpis" },
      kpi(r.unassigned_open, "open, unassigned", "#/reports", r.unassigned_open ? "warn" : ""), kpi(r.mine_open, "assigned to you", "#/reports"),
      kpi(r.aging_new_over_48h, "new for over 48 hours", "#/reports", r.aging_new_over_48h ? "bad" : ""), kpi(r.total, "reports in total", "#/reports"),
      kpi(d.watchlist.hits_exact, "exact watch-list hits", "#/watchlist", d.watchlist.hits_exact ? "bad" : ""), kpi(d.watchlist.hits_possible, "possible hits (partial reads)", "#/watchlist"),
      kpi(d.repeat_plates, "plates seen in 2+ videos", "#/sightings"), kpi(d.analyses.stored, "analyses stored", "#/analyses")),
    h("div", { class: "split" },
      h("section", { class: "panel" }, h("h3", {}, "Reports filed, last 7 days"), h("div", { class: "bars" }, r.per_day.map((x) => h("div", { class: "col" }, h("span", { class: "n" }, x.count || ""), h("i", { style: `height:${(x.count / max) * 100}%` }), h("span", { class: "l" }, x.date.slice(5)))))),
      h("section", { class: "panel" }, h("h3", {}, "By status"), brk(r.by_status, (k) => STATUS_LABEL[k] || pretty(k))),
      h("section", { class: "panel" }, h("h3", {}, "By agency"), brk(r.by_agency, (k) => AGENCY[k] || k))),
    me.role === "admin" ? h("section", { class: "panel" }, h("h3", {}, "Recent activity"),
      table(["When", "Who", "What", "On"], d.recent_activity.map((a) => h("tr", {}, h("td", {}, when(a.at)), h("td", {}, a.actor), h("td", { class: "mono-s" }, a.action), h("td", { class: "mono-s" }, a.target || ""))), "No activity yet."),
      h("p", { class: "hint-s" }, h("a", { href: "#/audit" }, "Open the full audit trail"))) : null);
}

/* ---------- reports ---------- */
let rf = { status: "", department: "", assigned: "", q: "" };
async function viewReports(view, openId) {
  const list = h("section", { class: "panel list-panel" });
  const detail = h("section", { class: "panel detail-panel" }, h("p", { class: "empty" }, "Choose a report from the list."));
  const sel = (id, opts, cur, onch) => { const s = h("select", { id, "aria-label": id }, opts.map(([v, l]) => h("option", { value: v, selected: v === cur }, l))); s.addEventListener("change", () => onch(s.value)); return s; };
  const q = h("input", { type: "search", placeholder: "Plate, ID, place, words…", value: rf.q, "aria-label": "Search reports" });
  let timer; q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { rf.q = q.value; load(); }, 250); });
  const csv = h("button", { class: "btn sm", type: "button" }, "Export CSV");
  csv.addEventListener("click", async () => { csv.disabled = true; try { await download("/api/desk/complaints.csv", "reports.csv"); } catch (e) { alert(e.message); } csv.disabled = false; });
  view.replaceChildren(head("Reports", "Citizen reports and vehicles flagged from the console. A registry match is a lead to verify, never a conclusion.", csv),
    h("div", { class: "op-tools" },
      field("Status", sel("rf-s", [["", "All statuses"], ...STATES.map((s) => [s, STATUS_LABEL[s]])], rf.status, (v) => { rf.status = v; load(); })),
      field("Agency", sel("rf-d", [["", "All agencies"], ...Object.entries(AGENCY).filter(([k]) => !me.agencies?.length || me.agencies.includes(k))], rf.department, (v) => { rf.department = v; load(); })),
      field("Assigned", sel("rf-a", [["", "Anyone"], ["me", "To me"], ["unassigned", "Unassigned"], ...team.map((t) => [t.username, t.name])], rf.assigned, (v) => { rf.assigned = v; load(); })),
      h("label", { class: "f grow" }, "Search", q)),
    h("div", { class: "desk-grid" }, list, detail));
  let selected = openId || null;
  async function load() {
    const p = new URLSearchParams(Object.entries(rf).filter(([, v]) => v));
    const rows = await call("/api/desk/complaints?" + p);
    list.replaceChildren(table(["Plate", "Report", "Assigned", "Status"], rows.map((r) => h("tr", { class: "click" + (r.id === selected ? " sel" : ""), tabindex: 0, onclick: () => open(r.id), onkeydown: (e) => { if (e.key === "Enter") open(r.id); } },
      h("td", { class: "mono" }, r.plate_confirmed || r.plate_read || "?", h("small", {}, r.plate_confirmed ? "typed by citizen" : r.source === "console" ? "fused from video" : "system read")),
      h("td", {}, r.source === "console" ? h("span", { class: "chip built", style: "margin-right:6px" }, "console") : null, r.related ? h("span", { class: "chip partial", style: "margin-right:6px", title: "Other reports about the same plate within 24 hours" }, `+${r.related} related`) : null, r.category_label.split("(")[0].trim(), h("small", { style: "display:block;color:var(--muted);font-size:11px" }, `${AGENCY[r.department]} · ${when(r.created_at)}`)),
      h("td", {}, r.assigned_to || h("span", { class: "muted" }, "none")), h("td", {}, chip(r.status)))), "No reports match these filters."));
  }
  async function open(id) {
    selected = id; history.replaceState(null, "", `#/reports/${id}`);
    blobs.splice(0).forEach(URL.revokeObjectURL);
    detail.replaceChildren(h("p", { class: "empty" }, h("span", { class: "spinner" }), "Loading…"));
    const [d, tl, rel] = await Promise.all([call(`/api/desk/complaints/${id}`), call(`/api/desk/complaints/${id}/timeline`), call(`/api/desk/complaints/${id}/related`)]);
    const [photo, crop] = await Promise.all([blobUrl(`/api/desk/complaints/${id}/photo`), d.plate_found ? blobUrl(`/api/desk/complaints/${id}/plate`) : null]);
    const m = d.match;
    const status = h("select", { "aria-label": "Status" }, d.statuses.map((s) => h("option", { value: s, selected: s === d.status }, STATUS_LABEL[s])));
    const who = h("select", { "aria-label": "Assigned to" }, h("option", { value: "" }, "Unassigned"), ...team.map((t) => h("option", { value: t.username, selected: t.username === d.assigned_to }, t.name)),
      d.assigned_to && !team.some((t) => t.username === d.assigned_to) ? h("option", { value: d.assigned_to, selected: true }, d.assigned_to) : null);
    const note = h("textarea", { maxlength: 1000, rows: 3, placeholder: "Add a note to the file (officers only)", "aria-label": "Note" });
    const msg = h("span", { class: "status-line", role: "status", "aria-live": "polite" });
    const act = async (fn, ok) => { say(msg, "Saving…"); try { await fn(); say(msg, ok); await Promise.all([load(), open(id)]); refreshBadges(); } catch (e) { say(msg, e.message, true); } };
    const map = d.lat != null ? h("a", { href: `https://www.openstreetmap.org/?mlat=${d.lat}&mlon=${d.lon}#map=17/${d.lat}/${d.lon}`, target: "_blank", rel: "noopener noreferrer" }, "open on a map ↗") : null;
    detail.replaceChildren(
      h("div", { class: "d-head" }, h("h3", { style: "margin:0" }, `Report ${d.id}`), chip(d.status)),
      h("p", { class: "muted", style: "font-size:13.5px;margin:6px 0 14px" }, `${d.category_label} · ${d.department_name} · filed ${when(d.created_at)}`),
      d.source === "console" ? h("p", { class: "from-console" }, h("span", { class: "chip built" }, "flagged from the console"), " ", h("a", { href: `/console/?job=${d.job_id}` }, `open analysis ${d.job_id}, vehicle ${d.track_id}`)) : null,
      h("div", { class: "d-imgs" }, photo ? h("img", { src: photo, alt: "Evidence photo", class: "preview" }) : h("p", { class: "empty" }, "Photo unavailable."), crop ? h("img", { src: crop, alt: "Plate crop", class: "crop-img" }) : null),
      h("h4", {}, d.source === "console" ? "Plate fused across the video's frames" : "System read of the photo"), slotsView(d.read_slots),
      d.plate_confirmed ? h("p", { class: "typed" }, "Citizen typed: ", h("span", { class: "mono" }, d.plate_confirmed)) : null,
      h("h4", { style: "margin-top:24px" }, "Registry match"), h("p", { class: "muted", style: "font-size:13px;margin-bottom:10px" }, `Basis: ${d.match_basis}.`), banner(m), m.candidates.map((c, i) => candidateView(c, i + 1)),
      h("h4", { style: "margin-top:24px" }, "Report details"),
      h("dl", { class: "dl" }, h("dt", {}, "Description"), h("dd", {}, d.description), h("dt", {}, "Location"), h("dd", {}, d.location_text, d.lat != null ? ` (${d.lat}, ${d.lon}) ` : "", map),
        h("dt", {}, "Observed"), h("dd", {}, d.observed_at ? when(d.observed_at) : "not given"), h("dt", {}, "Contact"), h("dd", {}, d.contact || "none given"),
        h("dt", {}, "Photo SHA-256"), h("dd", { class: "mono", style: "word-break:break-all;font-size:12px" }, d.image_sha256)),
      rel.length ? h("div", { class: "related" }, h("h4", { style: "margin-top:24px" }, `Same vehicle, ${rel.length} other report${rel.length > 1 ? "s" : ""} within 24 hours`),
        h("div", { class: "platechips" }, rel.map((x) => h("a", { class: "hit", href: `#/reports/${x.id}`, title: `${x.category_label} · ${when(x.created_at)}` }, `${x.id.slice(0, 6)} · ${x.status.replace("_", " ")}`)))) : null,
      h("h4", { style: "margin-top:24px" }, "Handling"),
      h("div", { class: "inline-form" }, field("Assigned to", who), h("button", { class: "btn sm", type: "button", onclick: () => act(() => call(`/api/desk/complaints/${id}/assign`, json("POST", { to: who.value || null })), "Assignment saved.") }, "Assign"),
        field("Status", status), h("button", { class: "btn sm", type: "button", onclick: () => act(() => call(`/api/desk/complaints/${id}`, json("PATCH", { status: status.value })), "Status saved.") }, "Update status"),
        h("button", { class: "btn sm", type: "button", onclick: () => act(() => call(`/api/desk/complaints/${id}/assign`, json("POST", { to: me.username })), "Assigned to you.") }, "Take it")),
      h("h4", { style: "margin-top:24px" }, "File history"),
      h("div", { class: "thread" }, tl.map((e) => h("div", { class: `ev ${e.kind}` }, h("small", {}, `${when(e.at)} · ${e.actor} · ${e.kind}`), e.text))),
      note, h("div", { class: "row-btns" }, h("button", { class: "btn primary sm", type: "button", onclick: () => { if (!note.value.trim()) return say(msg, "Write a note first.", true); act(() => call(`/api/desk/complaints/${id}/notes`, json("POST", { text: note.value })), "Note added."); } }, "Add note"), msg));
    if (innerWidth < 1000) detail.scrollIntoView({ behavior: UI.reduceMotion ? "auto" : "smooth" });
  }
  await load();
  if (selected) open(selected).catch((e) => detail.replaceChildren(h("p", { class: "err" }, e.status === 404 ? "No report with that ID." : e.message)));
}

/* ---------- analyses ---------- */
async function viewAnalyses(view) {
  const q = h("input", { type: "search", placeholder: "Find a plate in any stored video: UP14CA0914 or DL8C??4767", "aria-label": "Plate search" });
  const out = h("div", {});
  view.replaceChildren(head("Analyses", "Every video that was analysed, with its case file. Open one in the console to flag a vehicle."), h("section", { class: "panel" }, h("div", { class: "op-tools" }, h("label", { class: "f grow" }, "Plate", q)), out));
  let timer, seq = 0;
  async function load() {
    const mine = ++seq, rows = await api("/api/jobs" + (q.value.trim() ? `?plate=${encodeURIComponent(q.value.trim())}` : ""));
    if (mine !== seq) return;
    out.replaceChildren(table(["When", "File", "Agency", "Plates read", ""], rows.map((j) => h("tr", {}, h("td", {}, when(j.when)),
      h("td", {}, j.filename || h("span", { class: "muted" }, "(unnamed)"), h("small", { class: "mono", style: "display:block;color:var(--dim);font-size:11px" }, j.job_id)),
      h("td", {}, AGENCY[j.department] || j.department),
      h("td", {}, j.plates.length ? h("div", { class: "platechips" }, j.plates.map((p) => h("span", { class: j.matched_plates.includes(p) ? "hit" : "" }, p))) : h("span", { class: "muted" }, `none of ${j.vehicles}`)),
      h("td", {}, h("div", { class: "actions" }, h("a", { class: "btn sm", href: `/console/?job=${j.job_id}` }, "Open"), h("a", { class: "btn sm", href: `/api/jobs/${j.job_id}/report.pdf`, target: "_blank", rel: "noopener" }, "PDF"),
        h("a", { class: "btn sm", href: `/api/jobs/${j.job_id}/download`, download: `case-${j.job_id}.zip` }, "ZIP"))))), q.value.trim() ? "No stored video has a plate that fits that." : "Nothing analysed yet."));
  }
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 280); });
  await load();
}

/* ---------- watch-list ---------- */
async function viewWatchlist(view) {
  const plate = h("input", { class: "plate-input", maxlength: 12, placeholder: "UP14CA0914  or  DL8C??4767", autocomplete: "off", spellcheck: "false", "aria-label": "Plate" });
  const reason = h("input", { maxlength: 200, placeholder: "Why is it listed? (officers only)", "aria-label": "Reason" });
  const msg = h("p", { class: "status-line", role: "status", "aria-live": "polite" });
  const list = h("div", {}), hits = h("div", {});
  const form = h("form", { class: "inline-form" }, field("Plate", plate), h("label", { class: "f", style: "flex:2 1 260px" }, "Reason", reason), h("button", { class: "btn primary sm", type: "submit" }, "Add to watch-list"));
  const csvText = h("textarea", { rows: 4, placeholder: "plate,reason  (one per line; a header line is fine)\nUP14CA0914,Stolen, FIR 12\nDL8C??4767,Seen at border", "aria-label": "CSV rows" });
  const csvFile = h("input", { type: "file", accept: ".csv,text/csv,text/plain", "aria-label": "CSV file" });
  const csvReason = h("input", { maxlength: 200, placeholder: "Reason for rows that have none", "aria-label": "Default reason" });
  const csvMsg = h("p", { class: "status-line", role: "status", "aria-live": "polite" });
  csvFile.addEventListener("change", async () => { if (csvFile.files[0]) csvText.value = await csvFile.files[0].text(); });
  const importBox = h("section", { class: "panel" }, h("h3", {}, "Import a list"), h("div", { class: "inline-form" }, field("CSV file", csvFile), h("label", { class: "f", style: "flex:2 1 260px" }, "Default reason", csvReason)), csvText,
    h("div", { class: "row-btns" }, h("button", { class: "btn sm", type: "button", onclick: async () => {
      if (!csvText.value.trim()) return say(csvMsg, "Paste rows or choose a file first.", true);
      say(csvMsg, "Importing…");
      try { const r = await call("/api/desk/watchlist/import", json("POST", { csv: csvText.value, default_reason: csvReason.value })); csvText.value = ""; load(); refreshBadges();
        say(csvMsg, `${r.added} added${r.skipped.length ? `, ${r.skipped.length} skipped: ` + r.skipped.slice(0, 5).map((s) => `row ${s.row} (${s.plate || "empty"}): ${s.error}`).join(" · ") : ""}.`, r.skipped.length > 0 && r.added === 0); }
      catch (e) { say(csvMsg, e.message, true); } } }, "Import"), csvMsg));
  view.replaceChildren(head("Watch-list", "Plates to flag when they appear in any stored video. A hit is a lead to check against the video; “possible” means what was read agrees but some characters were unreadable. A character that was not read never creates a hit."),
    h("section", { class: "panel" }, form, msg), importBox, h("section", { class: "panel" }, h("h3", {}, "Listed plates"), list), h("section", { class: "panel" }, h("h3", {}, "Hits in stored videos"), hits));
  async function load() {
    const d = await call("/api/desk/watchlist");
    list.replaceChildren(table(["Plate", "Reason", "Listed", ""], d.entries.map((e) => h("tr", {}, h("td", { class: "mono" }, e.plate), h("td", {}, e.reason), h("td", {}, when(e.created_at)),
      h("td", {}, h("button", { class: "btn sm", type: "button", onclick: async () => { try { await call(`/api/desk/watchlist/${e.id}`, { method: "DELETE" }); load(); refreshBadges(); } catch (x) { say(msg, x.message, true); } } }, "Remove")))), "Nothing on the watch-list."));
    hits.replaceChildren(table(["Hit", "Listed plate", "Read as", "Video", "Reason"], d.alerts.map((a) => h("tr", {}, h("td", {}, h("span", { class: "chip " + (a.level === "exact" ? "verified" : "under_review") }, a.level)), h("td", { class: "mono" }, a.watch_plate), h("td", { class: "mono" }, a.read),
      h("td", {}, h("a", { href: `/console/?job=${a.job_id}` }, `${a.filename || a.job_id} #${a.track_id}`)), h("td", {}, a.reason))), d.entries.length ? "No stored video contains a plate that fits the list." : "Add a plate to start watching."));
  }
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try { await call("/api/desk/watchlist", json("POST", { plate: plate.value, reason: reason.value })); plate.value = ""; reason.value = ""; say(msg, "Added."); load(); refreshBadges(); } catch (e) { say(msg, e.message, true); }
  });
  await load();
}

/* ---------- repeat sightings ---------- */
async function viewSightings(view) {
  const groups = await api("/api/sightings");
  view.replaceChildren(head("Repeat sightings", "Plates seen in two or more different videos. Analysing one clip twice is not a repeat. A plate with unreadable characters is grouped only when nothing it did read disagrees."),
    h("section", { class: "panel" }, groups.length ? groups.map((g) => h("div", { class: "repeat" },
      h("div", { class: "repeat-head" }, h("span", { class: "mono repeat-plate" }, g.plate), h("span", { class: "chip" + (g.complete ? "" : " partial") }, g.complete ? "whole plate" : "partly read"),
        h("span", { class: "muted", style: "font-size:13px" }, `${g.footage_count} videos · first ${when(g.first_seen)} · last ${when(g.last_seen)}`),
        h("a", { class: "btn sm", href: `#/watchlist` }, "Watch-list")),
      h("div", { class: "platechips" }, g.sightings.map((x) => h("a", { class: "hit", href: `/console/?job=${x.job_id}` }, `${x.filename || x.job_id} #${x.track_id}`))))) : h("p", { class: "empty" }, "No plate has appeared in more than one video yet.")));
}

/* ---------- audit (admin) ---------- */
async function viewAudit(view) {
  const actor = h("input", { placeholder: "username", "aria-label": "Actor" }), action = h("input", { placeholder: "e.g. report, login, team", "aria-label": "Action" });
  const out = h("div", {});
  view.replaceChildren(head("Audit trail", "Who did what, newest first. Entries cannot be edited or deleted from here."), h("section", { class: "panel" }, h("div", { class: "op-tools" }, field("Who", actor), field("Action starts with", action)), out));
  let timer;
  async function load() {
    const p = new URLSearchParams({ limit: "300" }); if (actor.value.trim()) p.set("actor", actor.value.trim().toLowerCase()); if (action.value.trim()) p.set("action", action.value.trim());
    const rows = await call("/api/officer/audit?" + p);
    out.replaceChildren(table(["When", "Who", "Role", "Action", "On", "Detail"], rows.map((a) => h("tr", {}, h("td", { style: "white-space:nowrap" }, when(a.at)), h("td", {}, a.actor), h("td", {}, a.role), h("td", { class: "mono-s" }, a.action), h("td", { class: "mono-s" }, a.target || ""), h("td", {}, a.detail || ""))), "No entries match."));
  }
  [actor, action].forEach((i) => i.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 250); }));
  await load();
}

/* ---------- team (admin) ---------- */
async function viewTeam(view) {
  const list = h("div", {}), msg = h("p", { class: "status-line", role: "status", "aria-live": "polite" });
  const u = h("input", { placeholder: "e.g. asha.rao", autocomplete: "off", spellcheck: "false", "aria-label": "Username" }), n = h("input", { placeholder: "Full name", autocomplete: "off", "aria-label": "Name" });
  const role = h("select", { "aria-label": "Role" }, h("option", { value: "officer" }, "Officer"), h("option", { value: "admin" }, "Administrator"));
  const pw = h("input", { type: "text", placeholder: "At least 10 characters, mixed case, a digit", autocomplete: "off", "aria-label": "Temporary password" });
  const boxes = Object.entries(AGENCY).map(([k, v]) => h("label", { class: "chk" }, h("input", { type: "checkbox", value: k }), v));
  const form = h("form", { class: "inline-form" }, field("Username", u), field("Name", n), field("Role", role), field("Temporary password", pw),
    h("fieldset", { class: "agencies" }, h("legend", {}, "Agencies (none ticked = all)"), boxes),
    h("button", { class: "btn primary sm", type: "submit" }, "Create account"));
  const sess = h("div", {});
  view.replaceChildren(head("Team", "One account per officer, so every action is recorded under a person. Give the temporary password in person; they can change it under My account."),
    h("section", { class: "panel" }, form, msg), h("section", { class: "panel" }, h("h3", {}, "Accounts"), list),
    h("section", { class: "panel" }, h("h3", {}, "Signed-in sessions"), sess));
  async function loadSessions() {
    const rows = await call("/api/officer/sessions");
    sess.replaceChildren(table(["Who", "Role", "Signed in", "Expires", ""], rows.map((s) => h("tr", {}, h("td", {}, s.name, s.current ? h("span", { class: "chip built", style: "margin-left:8px" }, "you") : null), h("td", {}, s.role), h("td", {}, when(s.created_at)), h("td", {}, when(s.expires_at)),
      h("td", {}, s.current ? null : h("button", { class: "btn sm", type: "button", onclick: async () => { try { await call(`/api/officer/sessions/${s.id}`, { method: "DELETE" }); say(msg, "Session ended."); loadSessions(); } catch (e) { say(msg, e.message, true); } } }, "Sign out")))), "No active sessions."));
  }
  async function load() {
    loadSessions().catch(() => {});
    const rows = await call("/api/officer/team/all");
    team = rows.filter((o) => o.active).map((o) => ({ username: o.username, name: o.name, role: o.role }));
    list.replaceChildren(table(["Name", "Username", "Role", "Agencies", "Last sign-in", ""], rows.map((o) => h("tr", { class: o.active ? "" : "off" }, h("td", {}, o.name), h("td", { class: "mono-s" }, o.username),
      h("td", {}, o.role), h("td", {}, o.agencies.length ? o.agencies.map((a) => AGENCY[a] || a).join(", ") : "all"), h("td", {}, o.last_login ? when(o.last_login) : "never"),
      h("td", {}, h("div", { class: "act-row" },
        h("button", { class: "btn sm", type: "button", disabled: o.id === me.id, onclick: () => patch(o, { active: !o.active }, o.active ? "Account switched off and signed out." : "Account switched on.") }, o.active ? "Switch off" : "Switch on"),
        h("button", { class: "btn sm", type: "button", disabled: o.id === me.id, onclick: () => patch(o, { role: o.role === "admin" ? "officer" : "admin" }, "Role changed; they are signed out.") }, o.role === "admin" ? "Make officer" : "Make admin"),
        h("button", { class: "btn sm", type: "button", onclick: () => { const p = prompt(`Agencies for ${o.name}, comma separated from: ${Object.keys(AGENCY).join(", ")}. Leave empty for all.`, o.agencies.join(", ")); if (p !== null) patch(o, { agencies: p.split(",").map((x) => x.trim()).filter(Boolean) }, "Agencies saved; they are signed out."); } }, "Agencies"),
        h("button", { class: "btn sm", type: "button", onclick: () => { const p = prompt(`New temporary password for ${o.name} (10+ characters, mixed case, a digit):`); if (p) patch(o, { password: p }, "Password reset; they are signed out."); } }, "Reset password"))))), "No accounts yet. Create the first officer above."));
  }
  async function patch(o, body, ok) { try { await call(`/api/officer/team/${o.id}`, json("PATCH", body)); say(msg, ok); load(); } catch (e) { say(msg, e.message, true); } }
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try { await call("/api/officer/team", json("POST", { username: u.value, name: n.value, role: role.value, password: pw.value, agencies: boxes.map((b) => b.firstChild).filter((i) => i.checked).map((i) => i.value) })); u.value = n.value = pw.value = ""; say(msg, "Account created."); load(); } catch (e) { say(msg, e.message, true); }
  });
  await load();
}

/* ---------- my account ---------- */
async function viewAccount(view) {
  const cur = h("input", { type: "password", autocomplete: "current-password", "aria-label": "Current password" }), nw = h("input", { type: "password", autocomplete: "new-password", "aria-label": "New password" });
  const msg = h("p", { class: "status-line", role: "status", "aria-live": "polite" });
  const form = h("form", { class: "inline-form" }, field("Current password", cur), field("New password", nw), h("button", { class: "btn primary sm", type: "submit" }, "Change password"));
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try { await call("/api/officer/password", json("POST", { current: cur.value, new: nw.value })); cur.value = nw.value = ""; say(msg, "Password changed."); } catch (e) { say(msg, e.message, true); }
  });
  view.replaceChildren(head("My account", "Signed in sessions last 12 hours."),
    h("section", { class: "panel" }, h("dl", { class: "dl" }, h("dt", {}, "Name"), h("dd", {}, me.name), h("dt", {}, "Username"), h("dd", { class: "mono" }, me.username), h("dt", {}, "Role"), h("dd", {}, me.role), h("dt", {}, "Agencies"), h("dd", {}, me.agencies?.length ? me.agencies.map((a) => AGENCY[a] || a).join(", ") : "all"))),
    me.id === "key" ? h("section", { class: "panel" }, h("p", { class: "muted" }, "You are signed in with the master key, which has no password. Create your own administrator account under Team and use that day to day; keep the key for emergencies.")) :
      h("section", { class: "panel" }, h("h3", {}, "Change password"), form, msg));
}

/* ---------- start ---------- */
if (token) call("/api/officer/me").then(enter).catch(() => showLogin());
