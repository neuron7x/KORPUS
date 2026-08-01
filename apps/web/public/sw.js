const CACHE = "korpus-shell-__SHELL_DIGEST__";
const ASSETS = ["/", "/index.html", "/styles.css", "/app.js", "/config.js", "/manifest.webmanifest"];
self.addEventListener("install", event => event.waitUntil(
  caches.open(CACHE).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()),
));
self.addEventListener("activate", event => event.waitUntil(
  caches.keys()
    .then(keys => Promise.all(keys
      .filter(key => key.startsWith("korpus-shell-") && key !== CACHE)
      .map(key => caches.delete(key))))
    .then(() => self.clients.claim()),
));
self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (event.request.mode === "navigate") {
    event.respondWith(fetch(event.request).catch(() => caches.match("/index.html")));
    return;
  }
  if (ASSETS.includes(url.pathname)) {
    event.respondWith((async () => {
      try {
        const response = await fetch(event.request);
        if (response.ok) {
          const cache = await caches.open(CACHE);
          await cache.put(event.request, response.clone());
        }
        return response;
      } catch {
        return (await caches.match(event.request)) ?? Response.error();
      }
    })());
  }
});
