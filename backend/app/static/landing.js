"use strict";
const { $, $$, h, api, slotsView, candidateView, banner, sleep, reveal } = UI;

UI.initBar([["#how", "How it works"], ["#engine", "Live engine"], ["#departments", "Agencies"]]);
UI.initFoot();

/* depth on the hero: the image drifts with the cursor and scrolls slower than the page; the numerals scroll faster */
if (!UI.reduceMotion) {
  const hero = $(".hero"), bg = $(".hero-bg"), giant = $(".giant");
  let mx = 0, my = 0, queued = false;
  const paint = () => {
    queued = false;
    const y = Math.min(scrollY, innerHeight * 1.2);
    bg.style.setProperty("--bx", `${(-mx * 16).toFixed(1)}px`);
    bg.style.setProperty("--by", `${(-my * 9 + y * 0.16).toFixed(1)}px`);
    giant.style.setProperty("--gy", `${(-y * 0.07).toFixed(1)}px`);
  };
  const queue = () => { if (!queued) { queued = true; requestAnimationFrame(paint); } };
  if (matchMedia("(hover:hover)").matches) addEventListener("mousemove", (e) => { mx = e.clientX / innerWidth - 0.5; my = e.clientY / innerHeight - 0.5; queue(); }, { passive: true });
  addEventListener("scroll", queue, { passive: true });
}

/* ---------- how it works ---------- */
const STEPS = [
  ["Sample and track", "Frames are sampled six times a second. Each vehicle gets a track, so every piece of evidence stays attached to one car."],
  ["Find the plate", "A plate detector crops the plate in every frame. A plate under about 80 px wide is flagged as too small, never forced."],
  ["Read every frame", "Each character is read with its own confidence, limited to letters and digits, so doubt is visible instead of hidden."],
  ["Fuse across frames", "Frames vote on each position, weighted by confidence, sharpness and plate size. Doubtful positions stay as ?."],
  ["Match and rank", "The readable characters, colour and body type are compared with the registry. The top five come back with reasons."],
  ["Explain or refuse", "An agency-specific gate decides: match, ambiguous, or no confident match. The report lists every frame used."],
];
$("#steps").append(...STEPS.map(([t, d], i) => h("li", { class: "step rv", "data-rv": i % 3 === 0 ? "left" : i % 3 === 2 ? "right" : null }, h("div", { class: "n" }, String(i + 1).padStart(2, "0")), h("h3", {}, t), h("p", {}, d))));

/* ---------- shared data ---------- */
let monitorP, clearP;
const monitor = () => (monitorP ??= api("/api/monitor").catch(() => null));
const clearDemo = () => (clearP ??= (async () => {
  const frames = (await api("/data/demo_clear.json")).frames;
  const result = await api("/api/match", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ department: "police", frames }) });
  return { frames, result };
})().catch(() => null));

/* ---------- feature cards ---------- */
const CHIP = { built: "Built", partial: "Partial" };
function card({ chip = "built", title, text, vis, href, cta }) {
  const el = h(href ? "a" : "div", { class: "fcard rv", href }, h("div", { class: "top" }, h("span", { class: `chip ${chip}` }, CHIP[chip]), h("span", { class: "idx" }, "")),
    h("h3", {}, title), h("p", {}, text), h("div", { class: "vis" }, vis), cta ? h("span", { class: "go" }, cta + " →") : null);
  return el;
}
const mrow = (chars, cls = "") => h("div", { class: "mrow " + cls }, [...chars].map((c) => h("span", { class: c === "?" ? "q" : "" }, c)));

function fusionVisual() {
  const box = h("div", {}, h("p", { class: "muted", style: "font-size:12px" }, "Loading real frame reads…"));
  clearDemo().then((d) => {
    if (!d) { box.replaceChildren(h("p", { class: "muted", style: "font-size:12px" }, "Start the backend to see real frame reads.")); return; }
    const rows = d.frames.slice(0, 3).map((f) => mrow(f.chars.map((c) => (c ? c.char : "?")).join("")));
    box.replaceChildren(...rows, mrow(d.result.fused.slots.map((s) => s.char || "?").join(""), "fused"));
  });
  return box;
}

function refusalVisual() {
  const box = h("div", {}, h("p", { class: "muted", style: "font-size:12px" }, "Loading…"));
  clearDemo().then((d) => {
    if (!d) { box.replaceChildren(); return; }
    const m = /best score ([0-9.]+).*threshold of ([0-9.]+)/.exec(d.result.message);
    const score = m ? +m[1] : 0, thr = m ? +m[2] : 0.66;
    box.replaceChildren(h("span", { class: "chip no_confident_match", style: "justify-self:start" }, "No confident match"),
      h("div", { class: "gauge" }, h("i", { style: `width:${Math.round(score * 100)}%` }), h("s", { style: `left:${Math.round(thr * 100)}%` })),
      h("div", { class: "mini" }, h("span", {}, "best score ", h("b", {}, score.toFixed(2))), h("span", {}, "threshold ", h("b", {}, thr.toFixed(2)))));
  });
  return box;
}

function deptVisual() {
  const box = h("div");
  api("/api/departments").then((ds) => box.replaceChildren(...ds.map((d) => h("div", { class: "hbar", style: "grid-template-columns:74px 1fr 40px;padding:2px 0;font-size:12px" },
    h("span", {}, d.id.replace("_", "/").toUpperCase()), h("div", { class: "t" }, h("i", { style: `width:${d.match_threshold * 100}%` })), h("span", { class: "v" }, d.match_threshold.toFixed(2)))))).catch(() => {});
  return box;
}

function calibVisual() {
  const box = h("div");
  api("/api/calibration").catch(() => null).then((m) => {
    const c = m && m.agencies && m.agencies.police;
    if (!c) return;
    const W = 240, H = 64, pts = (key) => c.sweep.map((s, i) => `${(i / (c.sweep.length - 1) * W).toFixed(1)},${(H - 4 - s[key] * (H - 8)).toFixed(1)}`).join(" ");
    const ns = "http://www.w3.org/2000/svg", svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "spark"); svg.setAttribute("preserveAspectRatio", "none");
    svg.innerHTML = `<polyline fill="none" stroke="#ff2a3f" stroke-width="2" points="${pts("recall_top1")}"/><polyline fill="none" stroke="#8f99b0" stroke-width="2" stroke-dasharray="4 3" points="${pts("false_match_upper95")}"/>`;
    const r = c.recommended;
    box.replaceChildren(svg, h("div", { class: "mini" }, h("span", {}, "police θ ", h("b", {}, r.theta.toFixed(2))), h("span", {}, "recall ", h("b", {}, Math.round(r.recall_top1 * 100) + "%")), h("span", {}, "false ≤ ", h("b", {}, Math.round(r.false_match_upper95 * 100) + "%"))));
  });
  return box;
}

function reportVisual() {
  const box = h("div", {}, h("div", { class: "mini" }, h("span", {}, "Input SHA-256"), h("b", {}, "64 hex")), h("div", { class: "mini" }, h("span", {}, "Frames used"), h("b", {}, "listed")),
    h("div", { class: "mini" }, h("span", {}, "Characters per frame"), h("b", {}, "with confidence")), h("div", { class: "mini" }, h("span", {}, "Reasoning"), h("b", {}, "per candidate")));
  return box;
}
const flowVisual = (a, b, c, stat) => { const box = h("div", {}, h("div", { class: "flow" }, h("b", {}, a), "→", h("b", {}, b), "→", h("b", {}, c)), stat); return box; };

function buildCards() {
  const grid = $("#fgrid");
  const jobsStat = h("div", { class: "mini", style: "margin-top:8px" }, "…");
  const monStat = h("div", {}, h("div", { class: "big" }, "…"), h("div", { class: "mini" }, h("span", {}, "jobs analysed")));
  const reportCard = card({ title: "Audit report", text: "Every video is stored with its images and data, and downloads as one case file: a printable report, data tables, evidence frames, the original video and a hash manifest.", vis: reportVisual(), href: "/console/", cta: "Open the console" });
  monitor().then((m) => {
    if (!m) { jobsStat.textContent = "Start the backend for live numbers."; return; }
    jobsStat.replaceChildren(h("span", {}, "reports filed ", h("b", {}, m.complaints.total)));
    monStat.replaceChildren(h("div", { class: "big" }, String(m.jobs.tracks_readable)), h("div", { class: "mini" }, h("span", {}, "plates read in "), h("b", {}, `${m.jobs.total} jobs`)));
    if (m.jobs.recent[0]) { reportCard.href = `/api/jobs/${m.jobs.recent[0].job_id}/report`; reportCard.target = "_blank"; $(".go", reportCard).textContent = "Open a real report →"; }
  });
  const cards = [
    card({ title: "Multi-frame fusion", text: "Frames vote on each character, weighted by confidence, sharpness and plate size. Real reads from the Indian street clip are shown.", vis: fusionVisual() }),
    card({ title: "Unknown, never invented", text: "A position the evidence cannot settle stays as ?. On real footage the system left characters blank instead of guessing.", vis: h("div", {}, mrow("DL9CA??014", "fused"), h("p", { class: "muted", style: "font-size:12px;margin-top:6px" }, "Real output: two positions hidden by a hand over the plate.")) }),
    card({ title: "The refusal gate", text: "When nothing in the registry fits well enough, the answer is “no confident match”, with the score and the threshold that decided it.", vis: refusalVisual() }),
    card({ title: "Five agencies, one engine", text: "Police, MoRTH/NHAI, BSF, SSB and Customs share the engine and differ in threshold, required characters and allowed mismatches.", vis: deptVisual(), href: "#departments", cta: "See agencies" }),
    card({ title: "Calibrated by simulation", text: "Thresholds target each agency's false-match tolerance, using an upper confidence bound. The sightings are simulated and the noise model is an assumption, and we say so.", vis: calibVisual(), href: "/features/#deciding", cta: "How it works" }),
    reportCard,
    card({ title: "Citizen reports", text: "Anyone can photograph a vehicle. The plate is read, the citizen checks it, and the report goes to the right department. Citizens never see owner data.", vis: flowVisual("Photo", "Plate read", "Officer triage", jobsStat), href: "/report-issue/", cta: "Report an issue" }),
    card({ title: "Live monitoring", text: "Analyses, outcomes, plate size against readability, processing speed, server health and reports, all measured. Nothing on that page is sample data.", vis: monStat, href: "/monitor/", cta: "Open the monitor" }),
  ];
  cards.forEach((c, i) => { $(".idx", c).textContent = String(i + 1).padStart(2, "0"); });
  grid.append(...cards);
  reveal();
}
buildCards();

/* ---------- live engine ---------- */
const demo = { key: "partial", busy: false, started: false };
const NOTES = {
  partial: "Three frames of a registry plate with two characters hidden, plus one blurry frame that misreads a digit. The engine should rank the right vehicle first and leave the hidden positions unknown.",
  clear: "Real per-frame reads from our Indian street test clip (a white hatchback). This plate is not in the synthetic sample registry, so the right answer is a refusal, not a match.",
};

async function buildFrames(key) {
  if (key === "clear") return (await clearDemo())?.frames ?? (await api("/data/demo_clear.json")).frames;
  const plate = (await api("/api/registry/sample")).plate;
  const wrong = [..."0123456789"].find((d) => d !== plate[9]);
  const mk = (id, sharp, area, over = {}) => ({
    frame_id: id, sharpness: sharp, plate_area: area,
    chars: [...plate].map((c, i) => (i === 4 || i === 5 ? null : over[i] ? { char: over[i][0], conf: over[i][1] } : { char: c, conf: +(0.88 + (id % 3) * 0.04).toFixed(2) })),
  });
  return [mk(0, 110, 1000), mk(6, 95, 900), mk(12, 40, 450, { 9: [wrong, 0.42] }), mk(18, 120, 1100)];
}

function renderFrames(frames) {
  const box = $("#frames");
  box.replaceChildren(...frames.map((f) => h("div", { class: "frow" }, h("span", { class: "fid" }, `F${String(f.frame_id).padStart(3, "0")}`),
    f.chars.map((c) => (c ? h("span", { class: "cell", style: `background:rgba(255,42,63,${((1 - c.conf) * 0.5).toFixed(2)})` }, c.char, h("small", {}, c.conf.toFixed(2))) : h("span", { class: "cell none" }, "·"))))));
  return $$(".frow", box);
}

const emptySlots = () => $("#fused").replaceChildren(...Array.from({ length: 10 }, () => h("div", { class: "slot", role: "listitem" }, h("b", {}, "·"), h("small", {}, " "))));

async function runDemo() {
  if (demo.busy) return;
  demo.busy = true;
  const run = $("#run"), state = $("#demo-state");
  run.disabled = true;
  state.textContent = "running the real engine…";
  try {
    const frames = await buildFrames(demo.key);
    emptySlots();
    $("#verdict").replaceChildren();
    const rows = renderFrames(frames);
    const result = await api("/api/match", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ department: "police", frames }) });
    for (const r of rows) { r.classList.add("in"); await sleep(140); }
    await sleep(250);
    const els = $$("#fused .slot");
    for (const s of result.fused.slots) {
      const n = els[s.index];
      n.classList.add(s.char ? "known" : "unk");
      $("b", n).textContent = s.char || "?";
      $("small", n).textContent = s.confidence.toFixed(2);
      await sleep(90);
    }
    $("#verdict").replaceChildren(banner(result), ...result.candidates.slice(0, 1).map((c) => candidateView(c, 1, { reasons: 4 })));
    state.textContent = `${frames.length} frames, ${result.fused.slots.filter((s) => s.char).length} of 10 characters recovered`;
  } catch (e) {
    $("#verdict").replaceChildren(h("div", { class: "banner no_confident_match" }, h("b", {}, "Engine unreachable."), "Start the backend server to run this demo. " + e.message));
    state.textContent = "";
  } finally { run.disabled = false; demo.busy = false; }
}

function selectCase(key) {
  demo.key = key;
  $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.case === key)));
  $("#demo-note").textContent = NOTES[key];
  return runDemo();
}
$$(".tabs button").forEach((b) => b.addEventListener("click", () => selectCase(b.dataset.case)));
$("#run").addEventListener("click", runDemo);
$("#demo-note").textContent = NOTES.partial;
emptySlots();
new IntersectionObserver((es, obs) => { if (es.some((e) => e.isIntersecting) && !demo.started) { demo.started = true; obs.disconnect(); runDemo(); } }, { threshold: 0.3 }).observe($("#engine .demo"));

/* ---------- agencies ---------- */
const DEPT_META = {
  police: { blurb: "Leads for hit-and-run and violation cases, with an evidence report.", feats: [["done", "Evidence report with per-character confidence"], ["done", "Stolen and expired-document flags on candidates"], ["plan", "Watch-list alerts across cameras"]] },
  morth_nhai: { blurb: "Toll and highway compliance checks.", feats: [["done", "Insurance and PUC status flags on a confirmed match"], ["done", "Draft e-challan (PDF) for an officer to complete"], ["plan", "FASTag class mismatch check"]] },
  bsf: { blurb: "Border checkpoints, where a wrong match is worse than none.", feats: [["done", "Strict mode: no character mismatches allowed"], ["done", "Repeat sightings across stored videos"], ["plan", "Night-mode tuning"]] },
  ssb: { blurb: "Open-border traffic dominated by two-wheelers and small vehicles.", feats: [["part", "Body type weighted higher"], ["plan", "Crossing-frequency log"], ["plan", "Offline mode"]] },
  customs: { blurb: "Commercial vehicles, permits and routes.", feats: [["part", "Truck and tempo weighting"], ["plan", "Permit and route check"], ["plan", "Convoy detection"]] },
};
const FEAT = { done: "built", part: "partial", plan: "planned" };
(async () => {
  let list;
  try { list = await api("/api/departments"); } catch (_) { list = Object.keys(DEPT_META).map((id) => ({ id, name: id.toUpperCase(), match_threshold: null, min_known_chars: null })); }
  const meter = (label, frac, text) => h("div", { class: "meter" }, h("span", {}, label), h("i", {}, h("s", { style: `width:${Math.round((frac || 0) * 100)}%` })), h("em", {}, text));
  $("#depts").replaceChildren(...list.map((d) => {
    const m = DEPT_META[d.id] || { blurb: "", feats: [] };
    return h("article", { class: "panel dept rv" }, h("h3", {}, d.id.replace("_", " / ")), h("p", { class: "full" }, d.name), h("p", { class: "blurb" }, m.blurb),
      meter("Readable", (d.min_known_chars || 0) / 10, d.min_known_chars == null ? "-" : `${d.min_known_chars}/10`),
      meter("Threshold", d.match_threshold, d.match_threshold == null ? "-" : d.match_threshold.toFixed(2)),
      h("ul", { class: "feat" }, m.feats.map(([s, t]) => h("li", { class: s }, t, h("span", {}, FEAT[s])))));
  }));
  reveal();
})();

/* ---------- honest status ---------- */
const BOARD = [
  ["built", "Multi-frame plate recovery", "Frames vote per position, weighted by confidence, sharpness and plate size. Three plates on a real Indian street clip were read exactly."],
  ["built", "Unknown, never invented", "Doubtful characters stay as ?. On footage where plates were only 20 to 30 px wide, every position stayed unknown instead of being guessed."],
  ["built", "Registry ranking with reasons, and refusal", "Top five candidates with plain-English reasons. Plates missing from the registry were refused in every real-footage test."],
  ["built", "Citizen reports, officer portal and monitor", "Photo to plate read to department queue, with owner data visible only to signed-in officers. The monitor reads from saved jobs and reports, not sample data."],
  ["built", "Second-reader cross-check", "A second, unrelated pretrained reader checks every plate. On the real Indian clip it agreed on all five readable vehicles. It marks a plate for review if it disagrees, and never changes the plate. Plate-reading accuracy overall is still unmeasured on a labelled set."],
  ["weak", "Colour and body type", "Weak signals. Zero-shot body type was close to a coin flip on one real clip, so it carries a low weight."],
  ["built", "Plate grammar", "Plates are fitted to ten positions, and a 9-character plate with one series letter is now read as it is. Three series letters and short numbers are not handled."],
  ["partial", "Vehicle tracking", "One vehicle can split into several tracks. Tracks without a readable plate are collapsed in the results."],
  ["partial", "Agency features", "Per-agency strictness is live. Watch-lists, FASTag checks and repeat-crossing detection are still to come. Make and model, and cross-camera tracking, are bonus items not yet started."],
];
$("#board").append(...BOARD.map(([s, t, d]) => h("li", { class: "rv", "data-rv": "left" }, h("span", { class: `chip ${s}`, style: "justify-self:start" }, { built: "Built", partial: "Partial", weak: "Needs work" }[s]), h("div", {}, h("h3", {}, t), h("p", {}, d)))));
reveal();


/* ---------- marquee: loops forever, and runs faster while you scroll ---------- */
(function marquee() {
  const items = ["YOLOv8n", "ByteTrack", "YOLO11 plate detector", "PP-OCRv4", "second reader", "CLIP ViT-B/32", "multi-frame fusion", "unknown, never invented", "refusal gate", "SHA-256 case files"];
  const once = items.flatMap((t) => [h("span", {}, t), h("span", { class: "sep" }, "◆")]);
  const track = $("#marquee");
  track.append(...once, ...items.flatMap((t) => [h("span", {}, t), h("span", { class: "sep" }, "◆")]));
  if (UI.reduceMotion) return;
  const anim = track.getAnimations()[0];
  if (!anim) return;
  let last = scrollY, rate = 1;
  addEventListener("scroll", () => { rate = Math.min(9, 1 + Math.abs(scrollY - last) / 7); last = scrollY; }, { passive: true });
  (function ease() { rate += (1 - rate) * 0.06; anim.playbackRate = rate; requestAnimationFrame(ease); })();
})();

/* ---------- how it works: the rail fills with your scroll and each step lights when reached ---------- */
(function rail() {
  const sec = $("#how"), bar = $(".rail", sec), steps = $$(".step", sec);
  if (!sec || UI.reduceMotion) { steps.forEach((s) => s.classList.add("lit")); return; }
  let q = false;
  const paint = () => {
    q = false;
    const r = $("#steps").getBoundingClientRect(), vh = innerHeight;
    bar.style.setProperty("--prog", Math.min(1, Math.max(0, (vh * 0.78 - r.top) / (r.height + vh * 0.2))).toFixed(3));
    steps.forEach((s) => { const b = s.getBoundingClientRect(); s.classList.toggle("lit", b.top + b.height * 0.4 < vh * 0.78 && b.bottom > 0); });
  };
  addEventListener("scroll", () => { if (!q) { q = true; requestAnimationFrame(paint); } }, { passive: true });
  paint();
})();
