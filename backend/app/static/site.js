"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "style") n.style.cssText = v;
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return n;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, reduceMotion ? 0 : ms));

/* ---------- chrome: sections, pager, timeline, roman index ---------- */
const sections = $$("main > section");
const pagerBtns = $$("#pager button");
const roman = $("#roman");
let active = 0;

function setActive(i) {
  active = i;
  pagerBtns.forEach((b, k) => b.setAttribute("aria-current", String(k === i)));
  roman.textContent = sections[i].dataset.roman;
}
const io = new IntersectionObserver((entries) => {
  entries.forEach((e) => { if (e.isIntersecting) setActive(sections.indexOf(e.target)); });
}, { rootMargin: "-45% 0px -45% 0px" });
sections.forEach((s) => io.observe(s));

const revealIo = new IntersectionObserver((entries) => {
  entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); revealIo.unobserve(e.target); } });
}, { threshold: 0.15 });
$$(".rv").forEach((n, i) => { n.style.transitionDelay = reduceMotion ? "0s" : `${(i % 5) * 70}ms`; revealIo.observe(n); });

function goTo(id) {
  const t = document.getElementById(id);
  if (t) t.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
}
pagerBtns.forEach((b) => b.addEventListener("click", () => goTo(b.dataset.go)));
$$("[data-go]").filter((a) => a.tagName === "A").forEach((a) => a.addEventListener("click", (ev) => { ev.preventDefault(); goTo(a.dataset.go); }));

if (matchMedia("(hover:hover)").matches && !reduceMotion) {
  const bg = $("#bg");
  addEventListener("mousemove", (e) => {
    const x = e.clientX / innerWidth - 0.5, y = e.clientY / innerHeight - 0.5;
    bg.style.transform = `translate3d(${(-x * 18).toFixed(1)}px, ${(-y * 12).toFixed(1)}px, 0)`;
  }, { passive: true });
}

/* ---------- menu + legal ---------- */
const menu = $("#menu"), menuBtn = $("#menu-btn");
function setMenu(open) {
  menu.hidden = !open;
  menuBtn.setAttribute("aria-expanded", String(open));
  $("span", menuBtn).textContent = open ? "CLOSE" : "MENU";
  document.body.style.overflow = open ? "hidden" : "";
}
menuBtn.addEventListener("click", () => setMenu(menu.hidden));
$$("a", menu).forEach((a) => a.addEventListener("click", (ev) => {
  const h = a.getAttribute("href");
  setMenu(false);
  if (h && h.startsWith("#")) { ev.preventDefault(); goTo(h.slice(1)); }
}));
const legalBtn = $("#legal-btn"), legal = $("#legal");
legalBtn.addEventListener("click", () => {
  legal.hidden = !legal.hidden;
  legalBtn.setAttribute("aria-expanded", String(!legal.hidden));
});
addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!menu.hidden) { setMenu(false); menuBtn.focus(); }
  if (!legal.hidden) { legal.hidden = true; legalBtn.setAttribute("aria-expanded", "false"); }
});

/* ---------- live engine demo ---------- */
const demo = { key: "partial", frames: [], busy: false, started: false };
const NOTES = {
  partial: "Three frames of a registry plate with two characters hidden, and one blurry frame that misreads a digit. The engine should rank the right vehicle first and leave the hidden positions unknown.",
  clear: "Real per-frame reads from our Indian street test clip (a white hatchback). This plate is not in the synthetic sample registry, so the right answer is a refusal, not a match.",
};

async function getJson(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

async function buildFrames(key) {
  if (key === "clear") return (await getJson("data/demo_clear.json")).frames;
  const row = await getJson("/api/registry/sample");
  const plate = row.plate;
  const wrong = [..."0123456789"].find((d) => d !== plate[9]);
  const mk = (id, sharp, area, over = {}) => ({
    frame_id: id, sharpness: sharp, plate_area: area,
    chars: [...plate].map((c, i) => {
      if (i === 4 || i === 5) return null;
      if (over[i]) return { char: over[i][0], conf: over[i][1] };
      return { char: c, conf: +(0.88 + (id % 3) * 0.04).toFixed(2) };
    }),
  });
  return [mk(0, 110, 1000), mk(6, 95, 900), mk(12, 40, 450, { 9: [wrong, 0.42] }), mk(18, 120, 1100)];
}

function renderFrames(frames) {
  const box = $("#frames");
  box.replaceChildren(...frames.map((f) => el("div", { class: "frow" },
    el("span", { class: "fid" }, `FRAME ${f.frame_id}`),
    f.chars.map((c) => c
      ? el("span", { class: "cell", style: `background:rgba(255,45,85,${((1 - c.conf) * 0.45).toFixed(2)})` }, c.char, el("small", {}, c.conf.toFixed(2)))
      : el("span", { class: "cell none" }, "·")))));
  return $$(".frow", box);
}

function resetSlots() {
  $("#fused").replaceChildren(...Array.from({ length: 10 }, () => el("div", { class: "slot", role: "listitem" }, el("b", {}, "·"), el("small", {}, " "))));
  $("#verdict").replaceChildren();
}

const LABEL = { match: "Match", ambiguous: "Ambiguous, verify manually", no_confident_match: "No confident match", insufficient_evidence: "Insufficient evidence" };

function candidateView(c) {
  const plate = el("span", { class: "p" });
  [...c.plate].forEach((ch, i) => plate.append(el("span", { class: c.unknown_slots.includes(i) ? "unkc" : "" }, ch)));
  return el("div", { class: "cand" }, plate, el("span", { class: "sc" }, c.confidence.toFixed(2)),
    el("div", { style: "color:var(--muted);font-size:14px;margin-top:2px" }, `${c.make} ${c.model}, ${c.colour}, ${c.body_type.replace("_", " ")}`),
    el("ul", {}, c.reasons.slice(0, 4).map((r) => el("li", {}, r))));
}

async function runDemo() {
  if (demo.busy) return;
  demo.busy = true;
  const run = $("#run"), state = $("#demo-state");
  run.disabled = true;
  state.textContent = "running the real engine...";
  try {
    demo.frames = await buildFrames(demo.key);
    resetSlots();
    const rows = renderFrames(demo.frames);
    const result = await getJson("/api/match", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ department: "police", frames: demo.frames }),
    });
    for (const r of rows) { r.classList.add("in"); await sleep(140); }
    await sleep(250);
    const slotEls = $$("#fused .slot");
    for (const s of result.fused.slots) {
      const n = slotEls[s.index];
      n.classList.add(s.char ? "known" : "unk");
      $("b", n).textContent = s.char || "?";
      $("small", n).textContent = s.confidence.toFixed(2);
      await sleep(90);
    }
    const v = $("#verdict");
    v.replaceChildren(el("div", { class: `banner ${result.status}` }, el("b", {}, LABEL[result.status]), result.message),
      ...result.candidates.slice(0, 1).map(candidateView));
    state.textContent = `${demo.frames.length} frames, ${result.fused.slots.filter((s) => s.char).length} of 10 characters recovered`;
  } catch (e) {
    $("#verdict").replaceChildren(el("div", { class: "banner no_confident_match" }, el("b", {}, "Engine unreachable"), "Start the backend server to run this demo. " + e.message));
    state.textContent = "";
  } finally { run.disabled = false; demo.busy = false; }
}

async function selectCase(key) {
  demo.key = key;
  $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.case === key)));
  $("#demo-note").textContent = NOTES[key];
  await runDemo();
}
$$(".tabs button").forEach((b) => b.addEventListener("click", () => selectCase(b.dataset.case)));
$("#run").addEventListener("click", runDemo);
$("#demo-note").textContent = NOTES.partial;
resetSlots();
new IntersectionObserver((entries, obs) => {
  if (entries.some((e) => e.isIntersecting) && !demo.started) { demo.started = true; obs.disconnect(); runDemo(); }
}, { threshold: 0.35 }).observe($("#demo"));

/* ---------- departments ---------- */
const DEPT_META = {
  police: { blurb: "Leads for hit-and-run and violation cases, with an evidence report.",
    feats: [["done", "Evidence report with per-character confidence"], ["done", "Stolen and expired-document flags on candidates"], ["plan", "Watch-list alerts across cameras"]] },
  morth_nhai: { blurb: "Toll and highway compliance checks.",
    feats: [["part", "Insurance and PUC status flags"], ["plan", "FASTag class mismatch check"], ["plan", "Draft e-challan from the shortlist"]] },
  bsf: { blurb: "Border checkpoints, where a wrong match is worse than none.",
    feats: [["done", "Strict mode: no character mismatches allowed"], ["plan", "Repeat-crossing detection"], ["plan", "Night-mode tuning"]] },
  ssb: { blurb: "Open-border traffic dominated by two-wheelers and small vehicles.",
    feats: [["part", "Body type weighted higher"], ["plan", "Crossing-frequency log"], ["plan", "Offline mode"]] },
  customs: { blurb: "Commercial vehicles, permits and routes.",
    feats: [["part", "Truck and tempo weighting"], ["plan", "Permit and route check"], ["plan", "Convoy detection"]] },
};
const FEAT_LABEL = { done: "built", part: "partial", plan: "planned" };

async function renderDepts() {
  const box = $("#depts");
  let list = [];
  try { list = await getJson("/api/departments"); } catch (_) {
    list = Object.keys(DEPT_META).map((id) => ({ id, name: id.toUpperCase(), match_threshold: null, min_known_chars: null }));
  }
  box.replaceChildren(...list.map((d) => {
    const m = DEPT_META[d.id] || { blurb: "", feats: [] };
    const meter = (label, val, frac, text) => el("div", { class: "meter" }, el("span", {}, label),
      el("i", {}, el("s", { style: `width:${Math.round((frac || 0) * 100)}%` })), el("em", {}, text));
    return el("article", { class: "dept rv in" },
      el("h3", {}, d.id.replace("_", " / ")),
      el("p", { class: "full" }, d.name),
      el("p", { style: "margin:0 0 10px;font-size:14.5px;color:#c4c9d8" }, m.blurb),
      meter("Readable", d.min_known_chars, (d.min_known_chars || 0) / 10, d.min_known_chars == null ? "-" : `${d.min_known_chars}/10`),
      meter("Threshold", d.match_threshold, d.match_threshold, d.match_threshold == null ? "-" : d.match_threshold.toFixed(2)),
      el("ul", { class: "feat" }, m.feats.map(([s, t]) => el("li", { class: s }, t, el("span", {}, FEAT_LABEL[s])))));
  }));
}
renderDepts();

/* ---------- status board ---------- */
const BOARD = [
  ["built", "Multi-frame plate recovery", "Frames vote per slot, weighted by confidence, sharpness and plate size. Three of three plates on a real Indian street clip were read exactly."],
  ["built", "Unknown, never invented", "Doubtful characters stay as ?. On footage where plates were only 20 to 30 px wide, the system left every slot unknown instead of guessing."],
  ["built", "Registry ranking with reasons", "Top five candidates, each with a confidence score and a plain-English explanation of what matched and what did not."],
  ["built", "No-match handling", "Plates absent from the registry were refused in every real-footage test and in the simulated sweep at the configured thresholds."],
  ["partial", "Investigator console and report", "Upload a clip, review results, open a printable HTML report. PDF export is not built yet."],
  ["weak", "Colour and body type", "Weak signals. Zero-shot body type was close to a coin flip on one real clip, so it carries a low weight."],
  ["partial", "Department features", "Per-department strictness is live. Watch-lists, FASTag checks and repeat-crossing detection are still to come."],
  ["partial", "Vehicle tracking", "One vehicle can split into several tracks. Tracks without a readable plate are collapsed in the results."],
  ["planned", "Make and model, cross-camera tracking", "Bonus features, after the core is solid."],
];
const CHIP = { built: "Built", partial: "Partial", weak: "Needs work", planned: "Planned" };
$("#board").replaceChildren(...BOARD.map(([s, t, d]) => el("li", { class: "rv" },
  el("span", { class: `chip ${s}` }, CHIP[s]), el("div", {}, el("h3", {}, t), el("p", {}, d)))));
$$("#board .rv").forEach((n) => revealIo.observe(n));
