import { readFile, stat } from "node:fs/promises";
const required = ["public/index.html","public/app.js","public/styles.css","public/manifest.webmanifest","public/sw.js","public/config.js"];
for (const file of required) {
  const info = await stat(new URL(`../${file}`, import.meta.url));
  if (!info.isFile() || info.size === 0) throw new Error(`invalid web asset: ${file}`);
}
const html = await readFile(new URL("../public/index.html", import.meta.url), "utf8");
for (const marker of ['lang="uk"','id="query-form"','id="bearer-token"','id="login"','id="logout"','aria-live="polite"','/app.js']) {
  if (!html.includes(marker)) throw new Error(`web shell contract failed: ${marker}`);
}
const js = await readFile(new URL("../public/app.js", import.meta.url), "utf8");
for (const marker of ['Authorization', '/v1/auth/me', '/v1/auth/login', '/v1/auth/logout', 'X-CSRF-Token', 'credentials: "same-origin"', 'bearerToken', 'escapeHtml']) {
  if (!js.includes(marker)) throw new Error(`web security contract failed: ${marker}`);
}
if (/localStorage|sessionStorage/.test(js)) throw new Error("persistent token storage detected");
// RAG-019: retrieval_score is a ranking utility, not a calibrated probability. The UI
// renders it as a number, so the sentence that says what it is not must travel with it.
if (!js.includes("Ranking utility не є ймовірністю правильності")) throw new Error("uncalibrated score disclaimer missing");
if (js.includes("retrieval_score") && !js.includes("Ranking utility")) throw new Error("score rendered without its non-probability label");
if (!js.includes('readCookie("__Host-korpus_csrf")')) throw new Error("CSRF double-submit cookie contract missing");
if ((js.match(/document\.cookie/g) ?? []).length !== 1) throw new Error("browser must read only the CSRF cookie surface");
if (/readCookie\(["']__Host-korpus_session/.test(js)) throw new Error("HttpOnly session cookie must not be read by JavaScript");
const manifest = JSON.parse(await readFile(new URL("../public/manifest.webmanifest", import.meta.url), "utf8"));
if (!manifest.name || !manifest.start_url || manifest.display !== "standalone") throw new Error("PWA manifest contract failed");
console.log("web validation passed");
