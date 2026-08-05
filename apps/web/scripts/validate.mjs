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

// Accessibility contract. These are the properties a screen-reader or keyboard user
// depends on, and every one of them was absent until 2026-08-05 while the security
// contract above was fully enforced — the interface was verified for what it must not
// leak and not for whether it could be operated.
//
// Deliberately structural, not a scanner: axe or lighthouse need a browser, and a
// check that cannot run in the pipeline is a check that does not run. What is asserted
// here is what static structure can carry honestly. Contrast and focus order against a
// rendered page remain external, and are recorded as such in TECHNICAL_DEBT_V5.md.
const headings = [...html.matchAll(/<h([1-6])[^>]*>/g)].map((m) => Number(m[1]));
if (headings.filter((level) => level === 1).length !== 1) {
  throw new Error("accessibility: the page must have exactly one h1");
}
for (let index = 1; index < headings.length; index += 1) {
  if (headings[index] - headings[index - 1] > 1) {
    throw new Error(
      `accessibility: heading level jumps from h${headings[index - 1]} to h${headings[index]}; ` +
        "a screen reader's outline loses the skipped level",
    );
  }
}
// Every focusable control needs an accessible name. A button whose label is an icon or
// whose text is empty is announced as "button", which is not an instruction.
for (const [, attributes, text] of html.matchAll(/<button([^>]*)>([\s\S]*?)<\/button>/g)) {
  const named = text.replace(/<[^>]*>/g, "").trim().length > 0 ||
    /aria-label=|aria-labelledby=/.test(attributes);
  if (!named) throw new Error(`accessibility: button without an accessible name: ${attributes}`);
}
// Every text input needs a label bound by id. A placeholder disappears on typing and is
// not announced as a name.
for (const [, attributes] of html.matchAll(/<(?:input|textarea|select)([^>]*)>/g)) {
  if (/type="(hidden|submit|button)"/.test(attributes)) continue;
  const id = /id="([^"]+)"/.exec(attributes)?.[1];
  if (!id) throw new Error(`accessibility: form control without an id to label: ${attributes}`);
  if (!html.includes(`for="${id}"`) && !/aria-label=/.test(attributes)) {
    throw new Error(`accessibility: form control ${id} has no <label for> and no aria-label`);
  }
}
for (const [, attributes] of html.matchAll(/<img([^>]*)>/g)) {
  if (!/alt=/.test(attributes)) throw new Error(`accessibility: image without alt: ${attributes}`);
}
if (!/class="skip-link"[^>]*href="#/.test(html)) {
  throw new Error("accessibility: no skip link, so every navigation costs the header in tab stops");
}
if (!/<main[^>]*>/.test(html)) throw new Error("accessibility: no main landmark");
// The result panel is written by script after the answer arrives. Without a live
// region the update is silent for a screen reader: the page appears not to respond.
if (!/id="result"[^>]*aria-live="polite"/.test(html)) {
  throw new Error("accessibility: the result panel must announce itself when it is filled");
}
console.log("accessibility validation passed");
