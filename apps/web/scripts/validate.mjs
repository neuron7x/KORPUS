import { readFile, stat } from "node:fs/promises";
const required = [
  "public/index.html",
  "public/app.js",
  "public/styles.css",
  "public/manifest.webmanifest",
  "public/sw.js",
  "public/config.js",
];
for (const file of required) {
  const info = await stat(new URL(`../${file}`, import.meta.url));
  if (!info.isFile() || info.size === 0)
    throw new Error(`invalid web asset: ${file}`);
}
const html = await readFile(
  new URL("../public/index.html", import.meta.url),
  "utf8",
);
for (const marker of [
  'lang="uk"',
  'class="skip-link"',
  '<main id="top">',
  'id="query-form"',
  'id="bearer-token"',
  'id="login"',
  'id="logout"',
  'aria-live="polite"',
  'aria-atomic="false"',
  'maxlength="2000"',
  "production_authorized=false",
  "/app.js",
]) {
  if (!html.includes(marker))
    throw new Error(`web shell contract failed: ${marker}`);
}
if (/https?:\/\//.test(html))
  throw new Error("external web dependency detected");
const js = await readFile(new URL("../public/app.js", import.meta.url), "utf8");
for (const marker of [
  "Authorization",
  "/v1/auth/me",
  "/v1/auth/login",
  "/v1/auth/logout",
  "X-CSRF-Token",
  'credentials: "same-origin"',
  "bearerToken",
  "escapeHtml",
  "escapeHtml(citation.page)",
  "AbortController",
  "15000",
  "form.requestSubmit()",
]) {
  if (!js.includes(marker))
    throw new Error(`web security contract failed: ${marker}`);
}
if (/localStorage|sessionStorage/.test(js))
  throw new Error("persistent token storage detected");
if (!js.includes('readCookie("__Host-korpus_csrf")'))
  throw new Error("CSRF double-submit cookie contract missing");
if ((js.match(/document\.cookie/g) ?? []).length !== 1)
  throw new Error("browser must read only the CSRF cookie surface");
if (/readCookie\(["']__Host-korpus_session/.test(js))
  throw new Error("HttpOnly session cookie must not be read by JavaScript");
const css = await readFile(
  new URL("../public/styles.css", import.meta.url),
  "utf8",
);
for (const marker of [
  ":focus-visible",
  "prefers-reduced-motion",
  "prefers-contrast",
  "@media print",
]) {
  if (!css.includes(marker))
    throw new Error(`web accessibility contract failed: ${marker}`);
}
if (/url\(['"]?https?:/.test(css))
  throw new Error("external CSS dependency detected");
const totalBytes =
  Buffer.byteLength(html) + Buffer.byteLength(js) + Buffer.byteLength(css);
if (totalBytes > 40_000)
  throw new Error(`web shell budget exceeded: ${totalBytes} bytes`);
const manifest = JSON.parse(
  await readFile(
    new URL("../public/manifest.webmanifest", import.meta.url),
    "utf8",
  ),
);
if (!manifest.name || !manifest.start_url || manifest.display !== "standalone")
  throw new Error("PWA manifest contract failed");
console.log("web validation passed");
