const CACHE = "korpus-shell-v5";
// /api.js joined the list when app.js stopped carrying its own fetch handling: a module
// whose import is not cached fails to execute offline, which turns a degraded page into
// a blank one.
const ASSETS = ["/", "/index.html", "/styles.css", "/app.js", "/api.js", "/config.js", "/manifest.webmanifest"];
// The operator consoles are deliberately absent. They validate against a generated copy
// of the request contract, and a cached console is a console validating against rules
// the API may no longer have — the drift scripts/generate_web_contract.py exists to
// prevent, reintroduced by the cache.
self.addEventListener("install", event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS))));
self.addEventListener("activate", event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key))))));
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  event.respondWith(fetch(event.request).then(response => {
    if (response.ok && ASSETS.includes(url.pathname)) caches.open(CACHE).then(cache => cache.put(event.request, response.clone()));
    return response;
  }).catch(() => caches.match(event.request).then(response => {
    // Falling back to the query page for a console request would answer a request to
    // act with a page that only asks questions, and the operator would read it as the
    // console having been withdrawn from them.
    if (response) return response;
    if (url.pathname.startsWith("/console")) return Response.error();
    return caches.match("/index.html");
  })));
});
