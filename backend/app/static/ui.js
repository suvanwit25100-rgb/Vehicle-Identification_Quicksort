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
      slots.map((s, i) => h("div", { class: "slot " + (s.char ? "known" : "unk"), role: "listitem", style: `--i:${i}`, title: s.char ? `Read as ${s.char}` : "Unreadable, not guessed" },
        h("b", {}, s.char || "?"), small ? h("small", {}, (s.confidence ?? 0).toFixed(2)) : null)));
  }

  function plateView(c) {
    const el = h("span", { class: "plate" });
    [...c.plate].forEach((ch, i) => el.append(h("span", { class: (c.mismatched_slots || []).includes(i) ? "miss" : (c.unknown_slots || []).includes(i) ? "unkc" : "" }, ch)));
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

  function banner(result) {
    const label = STATUS_LABEL[result.status];
    // the engine's message often starts with the same words as the label; say them once
    let msg = result.message.replace(new RegExp("^" + label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "[.:,]?\\s*", "i"), "");
    msg = msg.charAt(0).toUpperCase() + msg.slice(1);
    return h("div", { class: `banner ${result.status}` }, h("b", {}, label + "."), msg);
  }

  /* ---------- nav + footer ---------- */
  const LINKS = [["/", "Overview", "home"], ["/features/", "Features", "features"], ["/console/", "Console", "console"], ["/monitor/", "Monitor", "monitor"], ["/archive/", "Archive", "archive"],
    ["/report-issue/", "Report an issue", "report"], ["/desk/", "Officer desk", "desk"]];

  function initBar(extra = []) {
    const bar = $("#bar");
    if (!bar) return;
    const page = document.body.dataset.page;
    const nav = h("nav", { class: "nav", id: "nav", "aria-label": "Main" },
      extra.map(([href, label]) => h("a", { href }, label)), extra.length ? h("span", { class: "nav-sep" }) : null,
      LINKS.map(([href, label, id]) => h("a", { href, "aria-current": id === page ? "page" : null }, label)));
    const btn = h("button", { class: "menu-btn", "aria-expanded": "false", "aria-controls": "nav" }, "MENU");
    btn.addEventListener("click", () => {
      const open = nav.classList.toggle("open");
      btn.setAttribute("aria-expanded", String(open));
      btn.textContent = open ? "CLOSE" : "MENU";
    });
    nav.addEventListener("click", (e) => { if (e.target.closest("a")) { nav.classList.remove("open"); btn.setAttribute("aria-expanded", "false"); btn.textContent = "MENU"; } });
    bar.innerHTML = "";
    bar.append(h("div", { class: "wrap" },
      h("a", { class: "glyph", href: "/", "aria-label": "Home" }, glyph(), h("span", {}, "AIML-01")), btn, nav));
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
      h("p", {}, "AIML-01 · Vehicle identification and traceability from CCTV footage. © 2026 Team Quicksort."),
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

  function initMotion() {
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
