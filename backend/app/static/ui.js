"use strict";
/* Shared helpers: DOM builder, API calls, nav bar, footer, and the plate/candidate views used on several pages. */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

  function h(tag, attrs = {}, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "style") n.style.cssText = v;
      else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return n;
  }

  async function api(path, opts = {}) {
    const r = await fetch(path, opts);
    if (!r.ok) {
      let detail = r.statusText;
      try { const j = await r.json(); detail = j.detail ?? detail; } catch (_) {}
      if (Array.isArray(detail)) detail = detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`).join("; ");
      const e = new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      e.status = r.status;
      throw e;
    }
    return r.json();
  }

  const STATUS_LABEL = {
    match: "Match", ambiguous: "Ambiguous, verify manually", no_confident_match: "No confident match", insufficient_evidence: "Insufficient evidence",
    new: "New", under_review: "Under review", verified: "Verified", forwarded: "Forwarded", closed: "Closed", rejected: "Rejected",
  };
  const pretty = (s) => String(s).replace(/_/g, " ");
  const topOf = (dist) => {
    if (!dist || !Object.keys(dist).length) return "unknown";
    const k = Object.keys(dist).sort((a, b) => dist[b] - dist[a])[0];
    return `${pretty(k)} (${dist[k].toFixed(2)})`;
  };

  /* slots: [{char|null, confidence}] -> the ten boxes. Unknown positions are amber and are never guessed. */
  function slotsView(slots, { small = true } = {}) {
    return h("div", { class: "slots", role: "list", "aria-label": "Plate characters" },
      slots.map((s, i) => { const absent = s.char === "-"; return h("div", { class: "slot " + (absent ? "absent" : s.char ? "known" : "unk"), role: "listitem", style: `--i:${i}`,
        title: absent ? "This plate has a single series letter, so this position is empty" : s.char ? `Read as ${s.char}` : "Unreadable, not guessed" },
        h("b", {}, absent ? "–" : s.char || "?"), small ? h("small", {}, absent ? "none" : (s.confidence ?? 0).toFixed(2)) : null); }));
  }

  function plateView(c) {
    const el = h("span", { class: "plate" });
    [...(c.slots || c.plate)].forEach((ch, i) => ch === "-" ? null : el.append(h("span", { class: (c.mismatched_slots || []).includes(i) ? "miss" : (c.unknown_slots || []).includes(i) ? "unkc" : "" }, ch)));
    return el;
  }

  function candidateView(c, rank, { reasons = 99 } = {}) {
    return h("div", { class: "cand" },
      h("div", { class: "cand-h" }, h("span", { class: "rank" }, `#${rank}`), plateView(c),
        (c.flags || []).map((f) => h("span", { class: "flag" }, pretty(f))),
        h("span", { class: "bar-s", role: "img", "aria-label": `confidence ${c.confidence.toFixed(2)}` }, h("i", { style: `width:${Math.round(c.confidence * 100)}%` })),
        h("span", { class: "score" }, c.confidence.toFixed(2))),
      h("div", { class: "sub" }, `${c.make} ${c.model}, ${c.colour}, ${pretty(c.body_type)} (registry ${c.reg_id})`),
      h("ul", {}, (c.reasons || []).slice(0, reasons).map((r) => h("li", {}, r))));
  }

  function banner(result, rto) {
    const label = STATUS_LABEL[result.status];
    // the engine's message often starts with the same words as the label; say them once
    let msg = result.message.replace(new RegExp("^" + label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "[.:,]?\\s*", "i"), "");
    msg = msg.charAt(0).toUpperCase() + msg.slice(1);
    return h("div", { class: `banner ${result.status}` }, h("b", {}, label + "."), msg, scoreRow(result, rto));
  }

  // Two numbers, kept apart: how sure we are of the plate we read (always shown), and how well the best registry entry fits (only if there is one).
  function scoreRow(result, rto) {
    const slots = (result.fused && result.fused.slots) || [];
    const expected = slots.filter((s) => s.char !== "-");
    const known = expected.filter((s) => s.char);
    const read = known.length ? known.reduce((a, s) => a + s.confidence, 0) / known.length : null;
    const best = (result.candidates || [])[0];
    const stat = (value, label) => h("div", { class: "stat" }, h("span", { class: "num" }, value), h("span", { class: "lab" }, label));
    const rtoStat = rto ? h("div", { class: `stat rto ${rto.status}`, title: rto.message },
      h("span", { class: "num" }, rto.status === "match" ? rto.confidence.toFixed(2) : "n/a"),
      h("span", { class: "lab" }, rto.status === "match" ? `RTO code match · ${rto.code} · ${rto.area} (${rto.office})` : `RTO code check · ${rto.message}`)) : null;
    return h("div", { class: "scores" },
      rtoStat,
      stat(read === null ? "n/a" : read.toFixed(2), `Plate read confidence · average of ${known.length} readable of ${expected.length} characters`),
      stat(best ? best.confidence.toFixed(2) : "none", best ? "Best registry fit (match confidence)" : "Best registry fit · no registry entry close enough"));
  }

  /* ---------- nav + footer ---------- */
  const LINKS = [["/", "Overview", "home"], ["/features/", "Features", "features"], ["/console/", "Console", "console"], ["/monitor/", "Monitor", "monitor"], ["/archive/", "Archive", "archive"],
    ["/report-issue/", "Report an issue", "report"], ["/officer/", "Officer portal", "officer"], ["/developers/", "API", "developers"]];

  function initBar(extra = []) {
    const bar = $("#bar");
    if (!bar) return;
    const page = document.body.dataset.page;
    const nav = h("nav", { class: "nav", id: "nav", "aria-label": "Main" },
      extra.map(([href, label]) => h("a", { href }, label)), extra.length ? h("span", { class: "nav-sep" }) : null,
      LINKS.map(([href, label, id]) => h("a", { href, "aria-current": id === page ? "page" : null }, label)));
    if (window.I18N) nav.append(I18N.button());
    const btn = h("button", { class: "menu-btn", "aria-expanded": "false", "aria-controls": "nav" }, "MENU");
    btn.addEventListener("click", () => {
      const open = nav.classList.toggle("open");
      btn.setAttribute("aria-expanded", String(open));
      btn.textContent = open ? "CLOSE" : "MENU";
    });
    nav.addEventListener("click", (e) => { if (e.target.closest("a")) { nav.classList.remove("open"); btn.setAttribute("aria-expanded", "false"); btn.textContent = "MENU"; } });
    bar.innerHTML = "";
    bar.append(h("div", { class: "wrap" },
      h("a", { class: "glyph", href: "/", "aria-label": "Home" }, glyph(), h("span", {}, "ExLex")), btn, nav));
    const onScroll = () => bar.classList.toggle("solid", scrollY > 30);
    addEventListener("scroll", onScroll, { passive: true });
    onScroll();
  }

  function glyph() {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", "0 0 32 32");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = '<circle cx="19" cy="14" r="9" fill="none" stroke="#eef1f8" stroke-width="1.6"/><circle cx="19" cy="14" r="3.2" fill="#ff2a3f"/><path d="M3 29 L13 20" stroke="#ff2a3f" stroke-width="2" stroke-linecap="round"/>';
    return svg;
  }

  function initFoot() {
    const f = $("#foot");
    if (!f) return;
    f.className = "foot";
    f.innerHTML = "";
    f.append(h("div", { class: "wrap" },
      h("p", {}, "ExLex · AIML-01 · Vehicle identification and traceability from CCTV footage. © 2026 Team Quicksort."),
      h("p", {}, "Confidence scores are uncalibrated estimates. Candidates are leads for an investigator to verify, not identifications. Characters that cannot be read are shown as ? and are never guessed.")));
  }

  /* ---------- motion ---------- */
  const html = document.documentElement;
  const hasIO = "IntersectionObserver" in window;
  const revealIo = hasIO ? new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting) { e.target.classList.add("in"); revealIo.unobserve(e.target); }
  }), { threshold: 0.1, rootMargin: "0px 0px -5% 0px" }) : null;

  /* stagger by position among revealing siblings, so a grid of cards cascades */
  function watch(el) {
    if (el.__watched) return;
    el.__watched = true;
    if (!el.classList.contains("rv")) el.classList.add("rv");
    if (!hasIO || reduceMotion) { el.classList.add("in"); return; }
    let idx = 0;
    for (let s = el.previousElementSibling; s && idx < 7; s = s.previousElementSibling) if (s.classList.contains("rv") && !s.classList.contains("in")) idx++;
    el.style.setProperty("--d", `${idx * 90}ms`);
    revealIo.observe(el);
  }

  const AUTO = ".page-head > *, .sec-head > *, main .panel:not(.step), .kpi, .fcard, .tile, .board li, .verdict > *, .stepper, .desk-bar, .feat-row, .evid, .rv";
  const SPOT = ".fcard, .tile, .step.rv, .dept, .kpi, .feat-row .vis";
  const TILT = ".fcard, .tile, .feat-row .vis";
  const DEPTH = ".feat-row .vis";

  /* headings rise word by word; the words keep their order and the heading keeps its full text for screen readers */
  function splitWords(el) {
    if (el.dataset.split) return;
    el.dataset.split = "1";
    const copy = el.cloneNode(true);   // a line break is not a space in textContent, so make it one before reading the text out
    copy.querySelectorAll("br").forEach((b) => b.replaceWith(" "));
    el.setAttribute("aria-label", copy.textContent.replace(/\s+/g, " ").trim());
    let i = 0;
    const walk = (node) => [...node.childNodes].forEach((c) => {
      if (c.nodeType === 3) {
        const frag = document.createDocumentFragment();
        c.textContent.split(/(\s+)/).forEach((tok) => {
          if (!tok) return;
          if (/^\s+$/.test(tok)) { frag.append(" "); return; }
          const w = document.createElement("span"), inner = document.createElement("span");
          w.className = "w"; w.setAttribute("aria-hidden", "true");
          inner.textContent = tok; inner.style.setProperty("--wi", i++);
          w.append(inner); frag.append(w);
        });
        c.replaceWith(frag);
      } else if (c.nodeType === 1 && c.tagName !== "BR") walk(c);
    });
    walk(el);
  }

  function annotate(root) {
    const nodes = root.matches && root.matches(AUTO) ? [root] : [];
    if (root.querySelectorAll) nodes.push(...root.querySelectorAll(AUTO));
    nodes.forEach((n) => {
      if (n.closest("[data-live][data-settled]") && !n.classList.contains("rv")) { n.classList.add("rv", "in"); n.__watched = true; return; }
      watch(n);
    });
    const spots = root.matches && root.matches(SPOT) ? [root] : [];
    if (root.querySelectorAll) spots.push(...root.querySelectorAll(SPOT));
    spots.forEach((n) => n.classList.add("spot"));
    const tilts = root.matches && root.matches(TILT) ? [root] : [];
    if (root.querySelectorAll) tilts.push(...root.querySelectorAll(TILT));
    tilts.forEach((n) => n.classList.add("tilt"));
    const heads = root.matches && root.matches(".h2") ? [root] : [];
    if (root.querySelectorAll) heads.push(...root.querySelectorAll(".h2"));
    if (!reduceMotion) heads.forEach(splitWords);
    const deep = root.matches && root.matches(DEPTH) ? [root] : [];
    if (root.querySelectorAll) deep.push(...root.querySelectorAll(DEPTH));
    deep.forEach((n) => { if (!reduceMotion) n.setAttribute("data-depth", "26"); });
  }

  function reveal() { annotate(document.body); $$(".rv").forEach(watch); }

  /* count a number up once it scrolls into view */
  function countUp(el, to, { duration = 1500, decimals = 0 } = {}) {
    const set = (v) => { el.textContent = Number(v).toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }); };
    if (reduceMotion || !hasIO) return set(to);
    set(0);
    const io = new IntersectionObserver((es) => {
      if (!es.some((e) => e.isIntersecting)) return;
      io.disconnect();
      const t0 = performance.now();
      const tick = (t) => { const p = Math.min(1, (t - t0) / duration); set(to * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(tick); };
      requestAnimationFrame(tick);
    }, { threshold: 0.4 });
    io.observe(el);
  }

  /* the second background and its lighting: image, drifting light, pulses on the streaks, grain, vignette, cursor glow */
  function initEnv() {
    if (document.querySelector(".env")) return;
    document.body.prepend(h("div", { class: "env", "aria-hidden": "true" }, h("div", { class: "env-bg" }),
      h("i", { class: "orb o1" }), h("i", { class: "orb o3" }), h("i", { class: "comet c1" }), h("i", { class: "comet c2" }),
      h("div", { class: "grain" }), h("div", { class: "vignette" }), h("div", { id: "cursorlight" })));
  }

  function initEffects() {
    if (reduceMotion) return;
    const bg = $(".env-bg"), env = $(".env"), hero = $(".hero");
    // scroll: the view climbs the streaks of the background image, depth elements float, the hero fades as you leave it
    let queued = false;
    const IMG_W = 736, IMG_H = 1308, FLARE = 0.72, STREAKS = [0.462, 0.537];   // measured from img/bg2.webp
    const frame = () => {
      queued = false;
      const y = scrollY, vh = innerHeight, vw = innerWidth;
      const max = document.documentElement.scrollHeight - vh, prog = max > 0 ? Math.min(1, Math.max(0, y / max)) : 0;
      const scale = Math.max(vw / IMG_W, vh / IMG_H), imgW = IMG_W * scale, imgH = IMG_H * scale, slack = Math.max(0, imgH - vh);
      const at = slack > 0 ? 0.66 - 0.3 * prog : 0.5;                 // where in the image the viewport looks: the flare at the top of the page, then up the streaks
      if (bg) bg.style.backgroundPosition = `50% ${(at * 100).toFixed(2)}%`;
      if (env) {
        const fy = FLARE * imgH - at * slack;                          // viewport row of the flare, so the pulses start from it
        env.style.setProperty("--fy", `${fy.toFixed(0)}px`);
        env.style.setProperty("--sx1", `${(vw / 2 + (STREAKS[0] - 0.5) * imgW).toFixed(1)}px`);
        env.style.setProperty("--sx2", `${(vw / 2 + (STREAKS[1] - 0.5) * imgW).toFixed(1)}px`);
        env.classList.toggle("nocomet", fy < vh * 0.22);
      }
      if (hero) hero.style.setProperty("--hp", Math.min(1, Math.max(0, y / (hero.offsetHeight * 0.8))).toFixed(3));
      $$("[data-depth]").forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.bottom < -80 || r.top > vh + 80) return;
        el.style.setProperty("--dy", `${(-((r.top + r.height / 2) / vh - 0.5) * Number(el.dataset.depth)).toFixed(1)}px`);
      });
    };
    addEventListener("scroll", () => { if (!queued) { queued = true; requestAnimationFrame(frame); } }, { passive: true });
    addEventListener("resize", () => { if (!queued) { queued = true; requestAnimationFrame(frame); } });
    frame();

    // section dividers draw themselves as each section comes into view
    if (hasIO) {
      const lit = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("lit"); lit.unobserve(e.target); } }), { threshold: 0.12 });
      $$(".sec").forEach((n) => lit.observe(n));
    }

    if (!matchMedia("(hover:hover)").matches) return;
    // a soft light that follows the cursor
    const light = $("#cursorlight");
    let tx = innerWidth / 2, ty = innerHeight / 2, x = tx, y = ty;
    addEventListener("pointermove", (e) => { tx = e.clientX; ty = e.clientY; light.classList.add("on"); }, { passive: true });
    document.documentElement.addEventListener("mouseleave", () => light.classList.remove("on"));
    (function loop() { x += (tx - x) * 0.09; y += (ty - y) * 0.09; light.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0)`; requestAnimationFrame(loop); })();

    // cards tilt towards the cursor; primary buttons lean towards it
    let tcur = null, bcur = null;
    const clear = (el, a, b) => { if (el) { el.style.setProperty(a, ""); el.style.setProperty(b, ""); } };
    document.addEventListener("pointermove", (e) => {
      const t = e.target.closest && e.target.closest(".tilt");
      if (tcur && tcur !== t) clear(tcur, "--rx", "--ry");
      tcur = t || null;
      if (t) { const r = t.getBoundingClientRect(), px = (e.clientX - r.left) / r.width, py = (e.clientY - r.top) / r.height; t.style.setProperty("--rx", `${((0.5 - py) * 7).toFixed(2)}deg`); t.style.setProperty("--ry", `${((px - 0.5) * 9).toFixed(2)}deg`); }
      const b = e.target.closest && e.target.closest(".btn.primary");
      if (bcur && bcur !== b) clear(bcur, "--mx2", "--my2");
      bcur = b || null;
      if (b) { const r = b.getBoundingClientRect(); b.style.setProperty("--mx2", `${((e.clientX - r.left - r.width / 2) * 0.18).toFixed(1)}px`); b.style.setProperty("--my2", `${((e.clientY - r.top - r.height / 2) * 0.28).toFixed(1)}px`); }
    }, { passive: true });
    document.documentElement.addEventListener("mouseleave", () => { clear(tcur, "--rx", "--ry"); clear(bcur, "--mx2", "--my2"); });
  }

  function initMotion() {
    initEnv();
    initEffects();
    // scroll progress bar
    const bar = h("div", { id: "progress", "aria-hidden": "true" });
    document.body.append(bar);
    let ticking = false;
    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        const max = document.documentElement.scrollHeight - innerHeight;
        bar.style.setProperty("--p", max > 0 ? (scrollY / max).toFixed(4) : 0);
        ticking = false;
      });
    };
    addEventListener("scroll", onScroll, { passive: true });
    onScroll();

    // cursor spotlight on cards
    if (matchMedia("(hover:hover)").matches && !reduceMotion) {
      document.addEventListener("pointermove", (e) => {
        const t = e.target.closest && e.target.closest(".spot");
        if (!t) return;
        const r = t.getBoundingClientRect();
        t.style.setProperty("--mx", `${e.clientX - r.left}px`);
        t.style.setProperty("--my", `${e.clientY - r.top}px`);
      }, { passive: true });
    }

    // things that appear later (fetched results, swapped panels) animate in too
    annotate(document.body);
    new MutationObserver((muts) => muts.forEach((m) => m.addedNodes.forEach((n) => { if (n.nodeType === 1) annotate(n); })))
      .observe(document.body, { childList: true, subtree: true });

    // page-to-page curtain
    html.classList.remove("leaving");
    if (html.classList.contains("arrived")) {
      requestAnimationFrame(() => requestAnimationFrame(() => { html.classList.remove("arrived"); html.classList.add("reveal"); }));
    }
    addEventListener("pageshow", (e) => { if (e.persisted) { html.classList.remove("leaving"); html.classList.add("reveal"); } });
    document.addEventListener("click", (e) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = e.target.closest && e.target.closest("a[href]");
      if (!a || a.target === "_blank" || a.hasAttribute("download")) return;
      const u = new URL(a.href, location.href);
      if (u.origin !== location.origin || u.pathname.startsWith("/api/")) return;
      if (u.pathname === location.pathname && u.search === location.search) return;
      e.preventDefault();
      if (reduceMotion) { location.href = a.href; return; }
      try { sessionStorage.setItem("nav", "1"); } catch (_) {}
      html.classList.remove("reveal");
      html.classList.add("leaving");
      setTimeout(() => { location.href = a.href; }, 500);
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initMotion); else initMotion();

  const sleep = (ms) => new Promise((r) => setTimeout(r, reduceMotion ? 0 : ms));
  const when = (iso) => { try { return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }); } catch (_) { return iso; } };

  window.UI = { $, $$, h, api, STATUS_LABEL, pretty, topOf, slotsView, plateView, candidateView, banner, initBar, initFoot, reveal, countUp, sleep, when, reduceMotion };
})();
