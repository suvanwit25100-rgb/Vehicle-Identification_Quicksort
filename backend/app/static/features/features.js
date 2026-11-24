"use strict";
const { $, h, api, candidateView, banner, pretty } = UI;
UI.initBar();
UI.initFoot();

/* ---------- live data, fetched once and shared ---------- */
let monitorP, clearP, partialP;
const monitor = () => (monitorP ??= api("/api/monitor").catch(() => null));
const match = (frames) => api("/api/match", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ department: "police", frames }) });
const clearDemo = () => (clearP ??= (async () => { const frames = (await api("/data/demo_clear.json")).frames; return { frames, result: await match(frames) }; })().catch(() => null));
const partialDemo = () => (partialP ??= (async () => {
  const plate = (await api("/api/registry/sample")).plate;
  const wrong = [..."0123456789"].find((d) => d !== plate[9]);
  const mk = (id, sharp, area, over = {}) => ({ frame_id: id, sharpness: sharp, plate_area: area,
    chars: [...plate].map((c, i) => (i === 4 || i === 5 ? null : over[i] ? { char: over[i][0], conf: over[i][1] } : { char: c, conf: +(0.88 + (id % 3) * 0.04).toFixed(2) })) });
  const frames = [mk(0, 110, 1000), mk(6, 95, 900), mk(12, 40, 450, { 9: [wrong, 0.42] }), mk(18, 120, 1100)];
  return { frames, result: await match(frames) };
})().catch(() => null));

const mrow = (chars, cls = "") => h("div", { class: "mrow " + cls }, [...chars].map((c) => h("span", { class: c === "?" ? "q" : "" }, c)));
const cap = (t) => h("p", { class: "cap" }, t);
const offline = () => h("p", { class: "cap" }, "Start the backend to see the live example.");
const slot = (promise, build) => { const box = h("div", { class: "livebox" }, h("p", { class: "cap" }, h("span", { class: "spinner" }), "Loading live example…")); promise.then((d) => box.replaceChildren(...(d ? build(d) : [offline()]))); return box; };

/* ---------- visuals ---------- */
const V = {
  fusion: () => slot(clearDemo(), (d) => [...d.frames.slice(0, 4).map((f) => mrow(f.chars.map((c) => (c ? c.char : "?")).join(""))), mrow(d.result.fused.slots.map((s) => s.char || "?").join(""), "fused"),
    cap("Real per-frame reads from the Indian street clip, then fused into one plate.")]),

  unknown: () => h("div", {}, mrow("DL9CA??014", "fused"), cap("Real output: a hand covered two positions, so they stay ? and the rest still count toward a match.")),

  grammar: () => {
    const kinds = "LLDALLDDDD", ex = "DL8CAY4767";
    const row = (txt, cls) => h("div", { class: "mrow" }, [...txt].map((c, i) => h("span", { class: cls(i) }, c)));
    return h("div", {}, row(kinds, (i) => "k k-" + kinds[i]), row(ex, (i) => "k k-" + kinds[i]),
      h("div", { class: "legend", style: "margin-top:10px" }, h("span", { style: "--c:var(--blue)" }, "letter"), h("span", { style: "--c:var(--green)" }, "digit"), h("span", { style: "--c:var(--amber)" }, "letter or digit")),
      cap("Position 4 can be a letter, as in Delhi's 1L and 8C, so it is never forced to a digit."));
  },

  tworow: () => h("div", {}, h("div", { class: "mrow fused", style: "width:62%" }, [..."DL14S"].map((c) => h("span", {}, c))), h("div", { class: "mrow fused", style: "width:62%" }, [..."Z8550"].map((c) => h("span", {}, c))),
    h("div", { class: "arrow" }, "↓ read each row as a line, then join"), mrow("DL14SZ8550", "fused"),
    cap("Measured on 300 generated two-row plates per setting: the old reader got 0%, the row-aware reader 82% (easier) and 66% (harder), fixing 247 and 197 plates and breaking none. One-row plates were identical before and after. On the real clip it read one clear two-row plate that was a fragment before.")),

  stitch: () => h("div", {}, mrow("UP14CA??14"), mrow("??14CA0914"), h("div", { class: "arrow" }, "↓ agree on 6 characters, clash on none"), mrow("UP14CA0914", "fused"),
    cap("Two fragments of one vehicle become one track. A single clash blocks the merge.")),

  small: () => h("div", {}, [[31, "too small"], [85, "readable"], [139, "readable"]].map(([px, s]) => h("div", { style: "margin-bottom:8px" },
    h("div", { class: "mini" }, h("span", {}, `plate ${px} px wide`), h("span", { class: "chip " + (s === "readable" ? "built" : "weak"), style: "padding:3px 8px" }, s)),
    h("div", { class: "gauge" }, h("i", { style: `width:${(px / 160) * 100}%` }), h("s", { style: "left:50%" })))),
    cap("The line marks 80 px. Below it the vehicle is listed with the reason, not read by guesswork.")),

  rank: () => slot(partialDemo(), (d) => [banner(d.result), ...d.result.candidates.slice(0, 1).map((c) => candidateView(c, 1, { reasons: 4 })), cap("Live: the real engine, run just now on a partly hidden registry plate.")]),

  gate: () => slot(clearDemo(), (d) => {
    const m = /best score ([0-9.]+).*threshold of ([0-9.]+)/.exec(d.result.message), score = m ? +m[1] : 0, thr = m ? +m[2] : 0.66;
    return [h("div", { class: "chips" }, ["match", "ambiguous", "no_confident_match", "insufficient_evidence"].map((s) => h("span", { class: `chip ${s}` }, UI.STATUS_LABEL[s]))),
      h("div", { class: "gauge", style: "margin-top:14px" }, h("i", { style: `width:${Math.round(score * 100)}%` }), h("s", { style: `left:${Math.round(thr * 100)}%` })),
      h("div", { class: "mini" }, h("span", {}, "best score ", h("b", {}, score.toFixed(2))), h("span", {}, "police threshold ", h("b", {}, thr.toFixed(2)))),
      cap("Live: a real plate that is not in the registry is refused, not forced into a match.")];
  }),

  attrs: () => slot((async () => {
    const m = await monitor();
    const id = m && m.jobs.recent.find((j) => j.readable)?.job_id;
    if (!id) return null;
    const job = await api(`/api/jobs/${id}`);
    return job.tracks.find((t) => t.colour && t.body_type) || null;
  })(), (t) => {
    const bars = (title, dist) => h("div", {}, h("p", { class: "label-s" }, title), ...Object.entries(dist).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, v]) => h("div", { class: "hbar", style: "grid-template-columns:90px 1fr 40px;padding:3px 0" }, h("span", {}, pretty(k)), h("div", { class: "t" }, h("i", { style: `width:${v * 100}%` })), h("span", { class: "v" }, v.toFixed(2)))));
    return [bars("Colour", t.colour), bars("Body type", t.body_type), cap("Real output. Body type was close to a coin flip on this clip, so it carries a low weight.")];
  }),

  calibration: () => slot(api("/api/calibration").catch(() => null), (m) => {
    const c = m.agencies && m.agencies.police;
    if (!c) return [offline()];
    const W = 260, H = 70, pts = (k) => c.sweep.map((s, i) => `${(i / (c.sweep.length - 1) * W).toFixed(1)},${(H - 4 - s[k] * (H - 8)).toFixed(1)}`).join(" ");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "spark"); svg.setAttribute("preserveAspectRatio", "none");
    svg.innerHTML = `<polyline fill="none" stroke="#ff2a3f" stroke-width="2" points="${pts("recall_top1")}"/><polyline fill="none" stroke="#8f99b0" stroke-width="2" stroke-dasharray="4 3" points="${pts("false_match_upper95")}"/>`;
    const r = c.recommended;
    return [svg, h("div", { class: "mini" }, h("span", {}, "police θ ", h("b", {}, r.theta.toFixed(2))), h("span", {}, "recall ", h("b", {}, Math.round(r.recall_top1 * 100) + "%")), h("span", {}, "false ≤ ", h("b", {}, Math.round(r.false_match_upper95 * 100) + "%"))),
      cap("Red: recall. Dashed: false matches. SIMULATED sightings, so a design target, not a measured accuracy.")];
  }),

  agencies: () => slot(api("/api/departments").catch(() => null), (ds) => [h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Agency", "Needs", "Threshold"].map((t) => h("th", {}, t)))),
    h("tbody", {}, ds.map((d) => h("tr", {}, h("td", {}, d.id.replace("_", " / ").toUpperCase()), h("td", { class: "mono" }, `${d.min_known_chars} of 10`), h("td", { class: "mono" }, d.match_threshold.toFixed(2))))))), cap("Live from the agency configuration file.")]),

  roadmap: () => h("div", {}, [["built", "Insurance and PUC status flags on a confirmed match"], ["built", "Watch-list with hits across stored videos"], ["built", "Repeat sightings across different videos"], ["built", "Draft e-challan (PDF) for an officer to complete"], ["planned", "FASTag class mismatch check"], ["planned", "Permit and route check (customs)"], ["planned", "Watch-list alerts across live cameras"]]
    .map(([s, t]) => h("div", { class: "mini", style: "padding:5px 0" }, h("span", {}, t), h("span", { class: `chip ${s}`, style: "padding:3px 8px" }, s)))),

  report: () => slot(monitor(), (m) => [h("div", { class: "flow" }, h("b", {}, "Photo"), "→", h("b", {}, "Plate read"), "→", h("b", {}, "You check it"), "→", h("b", {}, "Department queue")),
    h("div", { class: "big", style: "margin-top:10px" }, String(m.complaints.total)), h("div", { class: "mini" }, h("span", {}, "reports filed so far"))]),

  desk: () => h("div", {}, [["Photo and plate crop", "evidence"], ["System read and citizen-typed plate", "both shown"], ["Registry match with reasons", "officers only"], ["Status and note", "audit trail"]]
    .map(([a, b]) => h("div", { class: "mini", style: "padding:5px 0" }, h("span", {}, a), h("b", {}, b)))),

  privacy: () => h("div", {}, ["Citizens never see owner or registry data", "Explicit consent before anything is sent", "Photo location and time are only suggested", "Photo is re-encoded, dropping hidden metadata", "Rate limits per device", "Every officer route needs a key"]
    .map((t) => h("div", { class: "tick" }, h("i", {}, "✓"), t))),

  audit: () => slot(monitor(), (m) => [...[["Input SHA-256", "64 hex characters"], ["Frames used", "listed"], ["Characters per frame", "with confidence"], ["Reasoning", "per candidate"], ["Unreadable vehicles", "with the reason"]]
    .map(([a, b]) => h("div", { class: "mini", style: "padding:4px 0" }, h("span", {}, a), h("b", {}, b))),
    m.jobs.recent[0] ? h("a", { class: "btn sm", style: "justify-self:start;margin-top:10px", href: `/api/jobs/${m.jobs.recent[0].job_id}/report`, target: "_blank", rel: "noopener" }, "Open a real report ↗") : null]),

  monitor: () => slot(monitor(), (m) => [h("div", { class: "kpis", style: "grid-template-columns:repeat(3,1fr);gap:10px" }, [[m.jobs.total, "analyses"], [m.jobs.tracks_readable, "plates read"], [m.complaints.total, "reports"]].map(([n, l]) => h("div", {}, h("div", { class: "big" }, String(n)), h("div", { class: "mini" }, h("span", {}, l))))),
    cap("Read from saved jobs and reports. An empty chart means nothing has happened yet.")]),

  stack: () => slot(api("/api/brains").catch(() => null), (bs) => bs.map((b) => h("div", { class: "brainrow" }, h("div", {}, h("strong", {}, pretty(b.id)), h("p", { class: "cap", style: "margin:2px 0 0" }, `${b.role} · ${b.source} · ${b.license}`)), h("span", { class: "chip " + (b.ready ? "ready" : "missing") }, b.ready ? "ready" : "not installed")))),

  evidence: () => h("div", { class: "evid" },
    h("div", { class: "tablewrap" }, h("table", {}, h("thead", {}, h("tr", {}, ["Test", "Current reader", "fast-plate-ocr", "Awiros ANPR-OCR"].map((t) => h("th", {}, t)))),
      h("tbody", {}, [["10 real crops, exact", "70%", "70%", "80%"], ["300 synthetic, medium", "89%", "65%", "85%"], ["300 synthetic, hard", "69%", "30%", "70%"]].map((r) => h("tr", {}, r.map((c, i) => h("td", { class: i ? "mono" : "" }, c))))))),
    cap("Measured on 2026-11-24, one crop at a time. The real set is only 10 crops of 4 plates, so it proves little. The synthetic sets use fonts unlike real plates. When two readers agree they were right about 99% of the time on synthetic plates; that cross-check is not built yet.")),

  cross: () => slot(monitor(), (m) => {
    const c = m.jobs.cross_check, tot = c.agrees + c.disagrees + c.inconclusive;
    return [...[["agrees", "No clash, and at least 4 known characters confirmed", "built"], ["disagrees", "Any known character differs: verify by eye", "weak"], ["inconclusive", "Too little to compare", "partial"]]
      .map(([k, t, chip]) => h("div", { class: "mini", style: "padding:5px 0;gap:10px" }, h("span", {}, h("span", { class: `chip ${chip}`, style: "padding:3px 8px;margin-right:10px" }, k), t), h("b", {}, String(c[k])))),
      cap(tot ? `Live: ${tot} vehicle${tot === 1 ? "" : "s"} with a readable plate cross-checked so far.` : "No plates cross-checked yet. Analyse a clip to see it.")];
  }),

  casefile: () => slot(monitor(), (m) => [...[["report.html", "printable, self-contained"], ["report.pdf", "the same report as a PDF"], ["manifest.json", "hashes, models, settings"], ["data/*.csv", "vehicles, frames, candidates"], ["media/", "plates, vehicles, evidence frames"], ["source/", "the original video"]]
    .map(([a, b]) => h("div", { class: "mini", style: "padding:4px 0" }, h("b", { class: "mono", style: "font-weight:500" }, a), h("span", {}, b))),
    m.jobs.recent[0] ? h("a", { class: "btn sm", style: "justify-self:start;margin-top:10px", href: `/api/jobs/${m.jobs.recent[0].job_id}/download`, download: `case-${m.jobs.recent[0].job_id}.zip` }, "Download a real case file ↓") : null]),

  archive: () => slot(api("/api/jobs").catch(() => null), (jobs) => {
    const bytes = jobs.reduce((a, j) => a + j.size_bytes, 0);
    return [h("div", { class: "kpis", style: "grid-template-columns:repeat(3,1fr);gap:10px" }, [[jobs.length, "videos stored"], [(bytes / 1048576).toFixed(0), "MB on the server"], [jobs.filter((j) => j.has_video).length, "originals kept"]]
      .map(([n, l]) => h("div", {}, h("div", { class: "big" }, String(n)), h("div", { class: "mini" }, h("span", {}, l))))),
      cap("Live from the server. Search by a whole or partial plate to find the same vehicle in other videos.")];
  }),

  notbuilt: () => h("div", {}, ["Live camera streams: analysis is of uploaded clips", "Real registry (VAHAN) or FASTag data: the registry is synthetic", "Make and model recognition, and cross-camera tracking", "Individual officer accounts and citizen OTP sign-in", "Face blurring, retention and deletion rules", "Linking several citizens' reports of one vehicle", "Deleting stored analyses: videos stay until removed by hand"]
    .map((t) => h("div", { class: "tick off" }, h("i", {}, "–"), t))),
};

/* ---------- content ---------- */
const GROUPS = [
  ["reading", "Reading the plate", [
    ["built", "Multi-frame fusion", "One frame is never trusted. Every sampled frame of a vehicle votes on each plate position, and the votes are combined into one plate.",
      ["Votes are weighted by confidence, image sharpness and plate size", "A character needs a score of at least 0.60 and a 0.25 lead over the runner-up", "Anything short of that stays unknown"], "fusion", ["/#engine", "Watch it run"]],
    ["built", "Unknown, never invented", "When the evidence cannot settle a character, the system says so. A guessed plate sends an investigation after the wrong vehicle.",
      ["Unreadable positions are shown as ?, in amber, everywhere", "Matching uses only the characters that are known", "Plates too small to read stay entirely unknown"], "unknown"],
    ["built", "Plate grammar and alignment", "Indian plates follow a pattern. The system aligns every read to ten fixed positions, and corrects look-alike characters by where they sit.",
      ["Position 4 may be a letter or a digit (Delhi RTO codes such as 1L and 8C)", "O/0, I/1 and S/5 are corrected by position, with a confidence discount", "One extra or missing end character is tolerated", "A 9-character plate with a single series letter is read as it is: the empty second series position is shown as a gap, not as unreadable", "Still not handled: three series letters, and numbers shorter than four digits"], "grammar"],
    ["built", "Motorcycles and two-row plates", "Most Indian two-wheelers carry a two-row plate. A reader built for one line turns it into fragments, so each row is read as its own line and joined.",
      ["A plate that is not clearly one line is read both ways, and the reading that fits the plate format better wins", "A one-row plate is never split, so cars are unaffected (identical results in the measurement)", "Honest limits: tiny or blurry two-row plates still cannot be read, and only one clear two-row plate in our real clip could be checked"], "tworow"],
    ["built", "Repeat sightings and an officer watch-list", "The same vehicle seen in different videos is grouped on the archive page. Officers can list plates to flag, with a reason, and see where they appear.",
      ["Needs two different videos (by file hash): re-analysing one clip is not a repeat", "Unknown characters never create a hit: a partial read is only ever 'possible'", "The list and its reasons need the officer key and never appear in public responses", "Not built: live alerts; hits are shown on the desk on request"], "stitch"],
    ["built", "Agency next steps and a draft e-challan", "On a confirmed match only, each agency is told what the registry flags mean for it. Police and MoRTH/NHAI can open a draft e-challan PDF for an officer to complete.",
      ["Stolen: police verify first, other agencies refer it to the police", "Expired insurance or PUC: a draft challan, behind the officer key", "The draft has no fine amount, is watermarked, and nothing is sent anywhere", "The registry is synthetic, so the flags are demonstration data"], "rank"],
    ["built", "PDF report", "Every analysis can be downloaded as a PDF as well as a web page, and the PDF is also inside the case-file ZIP.",
      ["Same content: plate, confidence per slot, second reader, images, candidates, reasons, models", "Unknown characters stay ?", "Images are reduced for size; the ZIP keeps the originals"], "report"],
    ["partial", "Track stitching", "Trackers sometimes split one vehicle into several tracks. Fragments that clearly carry the same plate are joined.",
      ["Merge only if the plates agree on 6 or more characters and clash on none", "A group grows only if every pair in it is compatible", "Honest gap: on one real clip nothing needed merging, and unreadable fragments stay separate"], "stitch"],
    ["built", "Too small to read", "A vehicle with a tiny plate is not forced into a read. It is listed with the reason.",
      ["Plates under about 80 px wide are flagged", "The console lists every vehicle without a plate and why", "Plates that were 20 to 30 px wide stayed fully unknown on real footage"], "small"],
    ["built", "Independent second reader", "A second, different model reads the same plate crops. When two unrelated models agree, that is a strong sign; when they disagree, a person should look.",
      ["Its text is fitted to the same ten positions, so a plate of a different length is compared fairly", "Agrees: no clash and at least 4 known characters confirmed. Any clash: disagrees, verify manually", "It never changes the plate and never fills in a ?", "Honest limits: about 98% right when they agreed on synthetic plates; on 10 real crops they agreed on 7 and 6 were right"], "cross"],
  ]],
  ["deciding", "Deciding what it means", [
    ["built", "Ranked shortlist with reasons", "The readable characters, colour and body type are compared with the registry. The top five come back, each with a score and a plain-English explanation.",
      ["Plate fit is the summed confidence of the matched known characters, divided by 10", "Colour and body type are blended in with a per-agency weight", "A character that disagrees costs points", "Candidates carry flags such as stolen or expired"], "rank", ["/console/", "Open the console"]],
    ["built", "The refusal gate", "A shortlist is only called a match if it clears the agency's own bar. Otherwise the answer is that there is no confident match.",
      ["A minimum number of readable characters, set per agency", "A maximum number of mismatches among the known characters", "A minimum score, set per agency", "Four outcomes: match, ambiguous, no confident match, insufficient evidence"], "gate"],
    ["partial", "Colour and body type", "Soft supporting signals, not identifiers. Body type blends a vision-language model with the detector's class.",
      ["Colour comes from pixel analysis of the vehicle", "Body type uses CLIP zero-shot fused with the detector's class", "Honest gap: body type was close to a coin flip on real footage, so it carries a low weight"], "attrs"],
    ["built", "Calibrated by simulation", "Each agency's threshold is chosen to keep its false matches under a target, using an upper confidence bound rather than a lucky average.",
      ["Easy, medium and hard sightings, in-registry plates, look-alikes and random plates", "Wilson upper bound on the false-match rate", "The noise model is an assumption, so these are design targets"], "calibration"],
  ]],
  ["agencies", "Five agencies", [
    ["built", "One engine, five agencies", "Police, MoRTH/NHAI, BSF, SSB and Customs share one engine. They differ in how much evidence they need and how cautious they are.",
      ["Police accepts the most leads; BSF allows no character mismatches at all", "Thresholds come from each agency's tolerance for false matches", "Adding an agency is a configuration change"], "agencies", ["/#departments", "See the agencies"]],
    ["planned", "Agency-specific tools", "Each agency has its own working needs. Only some of these exist.",
      ["Stolen and expired-document flags on candidates: built", "Insurance and PUC flags: partial", "Everything else listed is planned, not built"], "roadmap"],
  ]],
  ["people", "Citizens and officers", [
    ["built", "Citizen reports", "Anyone can photograph a vehicle. The plate is read, the citizen checks it, and the report goes to the department that handles it.",
      ["Four steps: photo, check the plate, details, done", "A single photo has no fusion, so more characters stay unknown and the citizen can correct them", "Each category routes to an agency", "A status checker lets the citizen follow their report"], "report", ["/report-issue/", "Report an issue"]],
    ["built", "Officer desk", "Officers triage reports with the evidence in front of them.",
      ["Photo, plate crop, system read and the plate the citizen typed side by side", "A registry match with reasons, labelled as unverified", "Status and notes, filterable by status and agency"], "desk", ["/desk/", "Open the desk"]],
    ["built", "Privacy by design", "A report is a lead, not a verdict, and the person reporting must not become a way to look up owners.",
      ["Citizens never receive registry data, owner data or officer notes", "Consent is required, photos are limited to 10 MB, and each device is rate-limited", "Honest gap: one shared officer key and no face blurring yet"], "privacy"],
  ]],
  ["trust", "Trust and proof", [
    ["built", "Audit report", "Every analysis can be printed as one self-contained file that shows its working.",
      ["The SHA-256 of the input proves which file was analysed", "Frames used, and characters per frame with their confidence", "The reasoning for each candidate, and why unreadable vehicles had no plate"], "audit"],
    ["built", "Full case file for every video", "Everything about an analysed video is stored on the server and downloadable as one file: the report, the data, every image and the original video.",
      ["One ZIP with the printable report, three data tables for Excel, the plate, vehicle and evidence images, and the original video", "A manifest lists every file with its SHA-256, plus the models, software versions and agency settings used", "The video in the ZIP is byte-identical to the one analysed, and the manifest proves it"], "casefile", ["/archive/", "Open the archive"]],
    ["built", "Archive and plate search", "Nothing analysed is lost. Every video is listed, and a plate found in one video can be searched for in all the others.",
      ["Search with a whole or partial plate; ? stands for a character you cannot read", "Open, print or download any stored analysis", "Honest gap: nothing deletes stored videos yet, so they stay until removed by hand"], "archive", ["/archive/", "Search the archive"]],
    ["built", "Live monitor", "A page that shows what the system has really done: analyses, outcomes, plate size against readability, processing speed, reports, model files and the server's own health.",
      ["Every number is measured: stored analyses, reports, request counters and the machine; nothing is simulated", "Each panel says what it was drawn from, and an empty panel means nothing has happened", "Refreshes by itself; server counters restart with the server"], "monitor", ["/monitor/", "Open the monitor"]],
    ["built", "Automated tests", "Behaviour that must not break is covered by tests, not by promises.",
      ["Fusion, matching, stitching, calibration and the report", "Citizen and officer rules: privacy, keys, consent and limits", "Every page, and every local file each page uses"], null],
  ]],
  ["stack", "Under the hood", [
    ["built", "Pretrained models, none trained by us", "The system is built from ready-made models, and the work is in how their uncertainty is carried through.",
      ["Vehicles: YOLOv8n with ByteTrack. Plates: a YOLO11 plate detector", "Characters: PP-OCRv4 read with per-character confidence, checked by a second reader (fast-plate-ocr)", "Body type: CLIP ViT-B/32"], "stack"],
    ["partial", "Plate readers compared", "We tested two other pretrained plate readers against the current one.",
      ["None was clearly better alone, so none replaced the current reader", "Two readers agreeing was right about 98% of the time on synthetic plates, so one of them (fast-plate-ocr, 5 MB) now cross-checks every plate", "Awiros agreed more often and was right on every real agreement, but needs a heavy runtime, so it is not used"], "evidence"],
    ["planned", "Not built yet", "What the system does not do, stated plainly.", ["These are the gaps we know about"], "notbuilt"],
  ]],
];

const CHIP = { built: "Built", partial: "Partial", planned: "Planned" };
const groupsEl = $("#groups"), navEl = $("#fnav");
GROUPS.forEach(([id, title, rows], gi) => {
  navEl.append(h("a", { href: `#${id}` }, title));
  groupsEl.append(h("section", { class: "fgroup", id },
    h("div", { class: "fgroup-h rv" }, h("span", { class: "n" }, String(gi + 1).padStart(2, "0")), h("h2", {}, title)),
    rows.map(([status, name, text, bullets, vis, link], i) => h("article", { class: "feat-row rv", "data-rv": i % 2 ? "right" : "left" },
      h("div", { class: "txt" }, h("span", { class: `chip ${status}` }, CHIP[status]), h("h3", {}, name), h("p", {}, text),
        h("ul", {}, bullets.map((b) => h("li", {}, b))), link ? h("a", { class: "go", href: link[0] }, link[1] + " →") : null),
      h("div", { class: "vis" }, vis ? V[vis]() : h("div", { class: "tick" }, h("i", {}, "✓"), "Run `python -m pytest` in backend/"))))));
});

/* highlight the nav chip of the group that is in view */
const links = [...navEl.children];
const spy = new IntersectionObserver((es) => es.forEach((e) => {
  if (e.isIntersecting) links.forEach((a) => a.toggleAttribute("aria-current", a.getAttribute("href") === `#${e.target.id}`));
}), { rootMargin: "-35% 0px -55% 0px" });
[...groupsEl.children].forEach((s) => spy.observe(s));
