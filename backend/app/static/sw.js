/* ExLex service worker. It keeps the page shell (styles, scripts, the citizen pages) so the app opens quickly and opens even with no signal.
   It never stores anything from /api/ or any officer page: reports, plates and photos only ever come live from the server. */
const CACHE = "exlex-shell-v1";
const SHELL = ["/report-issue/", "/status/", "/offline.html", "/ui.css", "/pages.css", "/ui.js", "/i18n.js", "/pwa.js", "/report-issue/report.js", "/status/status.js", "/status/status.css", "/img/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin) return;                       // other sites (fonts, map tiles) and all writes go straight to the network
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/officer") || url.pathname.startsWith("/desk") || url.pathname === "/sw.js") return;   // never cached
  if (req.mode === "navigate") {
    e.respondWith(fetch(req).then((r) => { if (r.ok && SHELL.includes(url.pathname)) caches.open(CACHE).then((c) => c.put(req, r.clone())); return r; })
      .catch(() => caches.match(req).then((hit) => hit || caches.match("/offline.html"))));
    return;
  }
  e.respondWith(caches.match(req).then((hit) => {                                           // stale while revalidate for the shell's own files
    const fresh = fetch(req).then((r) => { if (r.ok && SHELL.includes(url.pathname)) caches.open(CACHE).then((c) => c.put(req, r.clone())); return r; }).catch(() => hit);
    return hit || fresh;
  }));
});
