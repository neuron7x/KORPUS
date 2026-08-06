// The development server. Static files, plus the one thing that made the two dev
// servers unusable together: /api/ never reached the API.
//
// In production nginx serves the assets and proxies `location /api/` to
// `http://api:8000/`, stripping the prefix. The browser therefore talks to a single
// origin, which is what `credentials: "same-origin"` and the `__Host-` cookie prefix
// require — both are meaningless across origins. Locally there was no equivalent:
// `make web-run` served :3000 and `make api-run` served :8000, config.js pointed at
// `/api`, and every request 404'd against the static server. Pointing config.js at
// :8000 instead would have "worked" only by moving the session cookie cross-origin,
// which is the security property, not a detail.
//
// So this mirrors the nginx rule exactly: same prefix, same strip, same single origin.
// It is a dev server — no rate limiting, no CSP, no TLS — and it says so on startup,
// because a dev proxy that looks like the production edge is how one ends up serving
// traffic.

import { createServer, request as httpRequest } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize } from "node:path";

const root = normalize(join(process.cwd(), process.argv[2] ?? "public"));
const apiOrigin = new URL(process.env.KORPUS_API_ORIGIN ?? "http://127.0.0.1:8000");
const port = Number(process.env.KORPUS_WEB_PORT ?? 3000);
const mime = {".html":"text/html; charset=utf-8",".js":"text/javascript; charset=utf-8",".css":"text/css; charset=utf-8",".json":"application/json",".webmanifest":"application/manifest+json"};

//: Mirrors `location /api/` in apps/web/nginx.conf: the prefix is stripped, so
//: /api/v1/answers reaches the API as /v1/answers. Getting this wrong sends
//: /api/v1/answers upstream and produces a 404 that reads like a missing route.
const API_PREFIX = "/api/";

function proxy(request, response, path) {
  const upstream = httpRequest(
    {
      protocol: apiOrigin.protocol,
      hostname: apiOrigin.hostname,
      port: apiOrigin.port,
      method: request.method,
      path: path.slice(API_PREFIX.length - 1) + (request.url.includes("?") ? `?${request.url.split("?").slice(1).join("?")}` : ""),
      headers: { ...request.headers, host: apiOrigin.host },
    },
    (upstreamResponse) => {
      response.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.headers);
      upstreamResponse.pipe(response);
    },
  );
  upstream.on("error", (error) => {
    // Named, not swallowed. "502" alone against a dev server almost always means the
    // API is not running, and saying so saves the reader a round through the browser
    // console and the network tab.
    response.writeHead(502, { "Content-Type": "application/json" });
    response.end(
      JSON.stringify({
        detail: `dev proxy could not reach ${apiOrigin.origin}: ${error.message}. Is \`make api-run\` running?`,
      }),
    );
  });
  request.pipe(upstream);
}

createServer(async (request, response) => {
  try {
    const raw = decodeURIComponent(new URL(request.url ?? "/", "http://localhost").pathname);
    if (raw.startsWith(API_PREFIX)) {
      proxy(request, response, raw);
      return;
    }
    let path = normalize(join(root, raw === "/" ? "index.html" : raw));
    if (!path.startsWith(root)) throw new Error("path traversal");
    try { if ((await stat(path)).isDirectory()) path = join(path,"index.html"); } catch { path = join(root,"index.html"); }
    response.writeHead(200,{"Content-Type":mime[extname(path)] ?? "application/octet-stream","Cache-Control":"no-store"});
    response.end(await readFile(path));
  } catch { response.writeHead(404); response.end("not found"); }
}).listen(port, "127.0.0.1", () => {
  console.log(`KORPUS web http://127.0.0.1:${port}`);
  console.log(`  consoles  http://127.0.0.1:${port}/console.html`);
  console.log(`  /api/ ->  ${apiOrigin.origin} (development proxy: no rate limit, no CSP, no TLS)`);
});
