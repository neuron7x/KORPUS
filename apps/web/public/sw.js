const CACHE = "korpus-shell-v83";
// Every module app.js imports must be cached: a module whose import is not cached fails to
// execute offline, and one missing file turns a degraded page into a blank one. /api.js
// joined when app.js stopped carrying its own fetch handling; /conversations.js joined
// with the conversation panel. validate.mjs enforces that this list covers every static
// import, so the next module cannot be forgotten here silently.
const ASSETS = ["/", "/index.html", "/tokens.css", "/styles.css",
  "/combat.css", "/combat_scene.js", "/trace.js", "/decision_field.css", "/decision_field.js", "/console.css", "/workspace.css", "/app.js", "/offline_controller.js", "/offline_store.js", "/chat_fsm.js", "/routes.js", "/offline_pack.js", "/workspace_routes.js",
  "/reader_verdicts.js",
  "/reader_conversations.js",
  "/reader_corpus.js",
  "/reader_declaration.js", "/billing.js", "/transport_contract.js", "/api.js", "/conversations.js", "/config.js", "/manifest.webmanifest"];
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
