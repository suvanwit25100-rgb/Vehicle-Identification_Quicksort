// Runs app/static/sw.js with a fake browser (cache, network, events) and prints what it did, as JSON.
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[2], "utf8");
const origin = "http://site.test";
const store = new Map();                          // cache name -> Map(url -> Response)
let online = true; const network = [];
const listeners = {};
const cachesApi = {
  open: async (n) => { if (!store.has(n)) store.set(n, new Map()); const m = store.get(n);
    return { addAll: async (urls) => { for (const u of urls) m.set(new URL(u, origin).href, new Response("shell:" + u)); }, put: async (req, res) => { m.set(req.url, res); },
             match: async (req) => m.get(typeof req === "string" ? new URL(req, origin).href : req.url) }; },
  keys: async () => [...store.keys()], delete: async (n) => store.delete(n),
  match: async (req) => { for (const m of store.values()) { const h = m.get(typeof req === "string" ? new URL(req, origin).href : req.url); if (h) return h.clone ? h.clone() : h; } },
};
const self = { addEventListener: (t, f) => { listeners[t] = f; }, skipWaiting: () => Promise.resolve(), clients: { claim: () => Promise.resolve() } };
const ctx = { self, caches: cachesApi, location: { origin }, URL, Response, fetch: async (req) => { network.push(req.url); if (!online) throw new Error("offline"); return new Response("live:" + new URL(req.url).pathname); } };
vm.createContext(ctx); vm.runInContext(src, ctx);

async function run(method, path, mode = "no-cors", cross = false) {
  const url = (cross ? "http://other.test" : origin) + path;
  const req = { method, url, mode }; let responded = null;
  listeners.fetch({ request: req, respondWith: (p) => { responded = Promise.resolve(p); } });
  if (!responded) return { handled: false };
  const res = await responded; return { handled: true, body: await res.text() };
}
(async () => {
  const out = {};
  const wait = []; await listeners.install({ waitUntil: (p) => wait.push(p) }); await Promise.all(wait);
  out.precached = [...store.get("exlex-shell-v1").keys()].map((u) => new URL(u).pathname);
  out.api = await run("GET", "/api/complaints/abc/progress"); out.officer = await run("GET", "/officer/"); out.desk = await run("GET", "/desk/"); out.sw = await run("GET", "/sw.js");
  out.post = await run("POST", "/report-issue/"); out.crossSite = await run("GET", "/x.png", "no-cors", true);
  out.navOnline = await run("GET", "/report-issue/", "navigate");
  online = false;
  out.navOffline = await run("GET", "/report-issue/", "navigate");                 // was visited online, so the cached copy is served
  out.navOfflineUnvisited = await run("GET", "/features/", "navigate");            // never cached: the offline page
  out.assetOffline = await run("GET", "/ui.css");
  out.apiOffline = await run("GET", "/api/health");
  out.cachedPaths = [...store.get("exlex-shell-v1").keys()].map((u) => new URL(u).pathname);
  // an old cache is removed on activation
  store.set("exlex-shell-v0", new Map()); const w2 = []; await listeners.activate({ waitUntil: (p) => w2.push(p) }); await Promise.all(w2); out.cachesAfterActivate = [...store.keys()];
  console.log(JSON.stringify(out));
})();
