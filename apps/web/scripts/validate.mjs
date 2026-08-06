import { readFile, stat } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const asset = (file) => fileURLToPath(new URL(`../${file}`, import.meta.url));
const read = (file) => readFile(asset(file), "utf8");

const DEV_SCRIPTS = ["scripts/serve.mjs", "scripts/build.mjs"];
const SCRIPTS = ["public/api.js", "public/app.js", "public/console.js", "public/console_rules.js", "public/contract.js", "public/sw.js"];
const PAGES = ["public/index.html", "public/console.html"];
const REQUIRED = [...PAGES, ...SCRIPTS, ...DEV_SCRIPTS, "nginx.conf", "public/styles.css", "public/manifest.webmanifest", "public/config.js"];

for (const file of REQUIRED) {
  const info = await stat(asset(file));
  if (!info.isFile() || info.size === 0) throw new Error(`invalid web asset: ${file}`);
}

// `node --check <file>` exits 0 for ANY file containing an `import` statement — the ESM
// retry path reports nothing. Verified on node v22.23.1 with a file holding both an
// import and `const y = ;`. The moment app.js became a module, `npm run lint` stopped
// checking it and kept printing success. Feeding the source on stdin with an explicit
// --input-type is the form that actually parses.
for (const file of [...SCRIPTS, ...DEV_SCRIPTS]) {
  const source = await read(file);
  const checked = spawnSync(process.execPath, ["--input-type=module", "--check"], {
    input: source,
    encoding: "utf8",
  });
  if (checked.status !== 0) {
    throw new Error(`syntax check failed for ${file}:\n${checked.stderr}`);
  }
}
console.log(`syntax check passed for ${SCRIPTS.length + DEV_SCRIPTS.length} modules`);

const html = await read("public/index.html");
for (const marker of ['lang="uk"','id="query-form"','id="bearer-token"','id="login"','id="logout"','aria-live="polite"','/app.js']) {
  if (!html.includes(marker)) throw new Error(`web shell contract failed: ${marker}`);
}

// ---------------------------------------------------------------- security contract
//
// The consoles (WEB-001) added a second page. Two pages meant two chances to hand-roll
// auth, and the second copy is where a token reaches localStorage or a POST goes out
// without its CSRF header. So the contract moved: api.js is the only module allowed to
// touch credentials or the network, and every other script is checked for *absence*.
const api = await read("public/api.js");
for (const marker of ['Authorization', 'X-CSRF-Token', 'credentials: "same-origin"', 'bearerToken', 'escapeHtml']) {
  if (!api.includes(marker)) throw new Error(`web security contract failed: ${marker}`);
}
if (!api.includes('readCookie("__Host-korpus_csrf")')) throw new Error("CSRF double-submit cookie contract missing");
if ((api.match(/document\.cookie/g) ?? []).length !== 1) throw new Error("browser must read only the CSRF cookie surface");
if (/readCookie\(["']__Host-korpus_session/.test(api)) throw new Error("HttpOnly session cookie must not be read by JavaScript");
// A state-changing request must not be able to leave without the CSRF header, so the
// header is attached by method inside api.js rather than by each caller remembering.
if (!/\["GET", "HEAD", "OPTIONS"\]\.includes\(method\)/.test(api)) {
  throw new Error("CSRF header must be attached by method, not by the caller opting in");
}

const app = await read("public/app.js");
const consoleJs = await read("public/console.js");
const consoleRules = await read("public/console_rules.js");
for (const [name, source] of [["app.js", app], ["console.js", consoleJs]]) {
  if (/\bfetch\s*\(/.test(source)) {
    throw new Error(`${name} calls fetch directly; every request must go through api.js`);
  }
  if (/document\.cookie/.test(source)) {
    throw new Error(`${name} reads cookies directly; the CSRF surface lives in api.js`);
  }
  if (!/from "\.\/api\.js"/.test(source)) {
    throw new Error(`${name} must obtain its API access from api.js`);
  }
}
// Matches use, not mention. The bare-word form tripped on api.js's own comment
// explaining why a token must never reach localStorage — a guard that forbids naming
// the hazard it guards against, which is how the explanation gets deleted instead of
// the hazard. The trailing class covers `localStorage.x`, `localStorage[k]`,
// `f(localStorage)` and `const s = localStorage;`, the ways a reference is actually
// taken.
const PERSISTENT_STORAGE = /(localStorage|sessionStorage)\s*[.[;)=,]/;
for (const file of ["public/api.js", "public/app.js", "public/console.js", "public/console_rules.js"]) {
  if (PERSISTENT_STORAGE.test(await read(file))) {
    throw new Error(`persistent token storage detected in ${file}`);
  }
}

// ---------------------------------------------------------------- reader surface
//
// The identity the server verified and the identity the operator declared are two
// different things, and the interface has to keep saying so. Access is decided by the
// OIDC subject and the entitlement profile; the name and specialty are typed on a
// keyboard. NIST SP 800-63-3 separates identity proofing from authentication, and a
// page that prints them as one line has asserted a proofing level nobody performed.
if (!/class="chip verified"/.test(html) || !/class="chip declared"/.test(html)) {
  throw new Error("the reader surface no longer distinguishes verified from declared");
}
if (!/\.chip\.declared \{[^}]*dashed/.test(await read("public/styles.css"))) {
  throw new Error("a declared attribute is styled like a verified one");
}
if (!/Система їх не перевіряє/.test(html)) {
  throw new Error("the declaration form no longer says the system does not verify it");
}
// The declaration must reach the audit chain, not sit in the browser: an investigator
// asking "who asked this" needs both the token's subject and the name at the keyboard.
if (!/body: \{text: query\.value, declaration\}/.test(app)) {
  throw new Error("the declaration no longer travels with the query");
}
// Error summary above the form, focusable, linking to the field (WCAG 2.2 §3.3.1,
// USWDS pattern). A message only beside the input is missed by a screen reader that has
// moved past it and by anyone below the fold.
if (!/id="entry-errors"[^>]*role="alert"[^>]*tabindex="-1"/.test(html)) {
  throw new Error("no focusable error summary on the reader surface");
}
if (!/errors\.focus\(\)/.test(app) || !/href="#\$\{escapeHtml\(field\)\}"/.test(app)) {
  throw new Error("the error summary does not move focus or link to its fields");
}
// `hidden` is an attribute, not a suggestion: `.standing { display: flex }` out-specifies
// the user-agent rule, and the collapsed sections rendered anyway on first paint.
if (!/\[hidden\] \{ display: none !important; \}/.test(await read("public/styles.css"))) {
  throw new Error("hidden sections can be overridden by a display rule");
}
// A refusal is the system working. Rendering it as an error trains operators to retry
// until they get prose.
if (!/ПІДСТАВИ НЕМАЄ/.test(app)) {
  throw new Error("the withheld verdict no longer has its own wording");
}

// RAG-019: retrieval_score is a ranking utility, not a calibrated probability. The UI
// renders it as a number, so the sentence that says what it is not must travel with it.
if (!app.includes("Ranking utility не є ймовірністю правильності")) throw new Error("uncalibrated score disclaimer missing");
if (app.includes("retrieval_score") && !app.includes("Ranking utility")) throw new Error("score rendered without its non-probability label");

const manifest = JSON.parse(await read("public/manifest.webmanifest"));
if (!manifest.name || !manifest.start_url || manifest.display !== "standalone") throw new Error("PWA manifest contract failed");

// ---------------------------------------------------------------- console contract
//
// WEB-001's acceptance predicate is that every critical workflow runs without raw DB or
// API manipulation. Reaching it needs more than the forms existing.
const consoleHtml = await read("public/console.html");
for (const id of [
  "console-curator", "console-reviewer", "console-corpus", "console-auditor",
  "ingest-form", "review-form", "rescind-form", "audit-events-form",
]) {
  if (!consoleHtml.includes(`id="${id}"`)) throw new Error(`operator console missing surface: ${id}`);
}
// Nothing irreversible fires on a first click. Each of the three writing workflows has a
// preview button and a submit that ships disabled.
for (const workflow of ["ingest", "review", "rescind"]) {
  if (!consoleHtml.includes(`id="${workflow}-preview"`)) {
    throw new Error(`${workflow} has no preview: an irreversible action would fire on first click`);
  }
  if (!new RegExp(`id="${workflow}-submit"[^>]*disabled`).test(consoleHtml)) {
    throw new Error(`${workflow} submit is enabled before anything was previewed`);
  }
}
// Every console is reachable. The tabs replaced a single long scroll on 2026-08-06;
// a tab whose panel it cannot select is a console that exists and cannot be opened.
for (const name of ["console-curator", "console-reviewer", "console-corpus", "console-auditor"]) {
  if (!consoleHtml.includes(`id="tab-${name}"`)) {
    throw new Error(`console ${name} has no tab, so it cannot be reached`);
  }
  if (!new RegExp(`id="tab-${name}"[^>]*aria-controls="${name}"`).test(consoleHtml)) {
    throw new Error(`the tab for ${name} does not name the panel it controls`);
  }
}
// Every outcome panel starts with a sentence. An empty panel beside a form reads both
// as "nothing has happened yet" and as "it ran and produced nothing".
for (const id of [
  "ingest-result", "job-result", "review-result", "rescind-result",
  "documents-result", "spans-result", "audit-verify-result", "audit-events-result",
]) {
  if (!consoleJs.includes(`"${id}":`)) {
    throw new Error(`${id} has no idle text, so an empty panel is ambiguous`);
  }
}

// The gate compares the previewed payload with the one about to be sent. A boolean
// "was previewed" flag would let an edit slip between confirmation and submission.
if (!/previewMatches\(confirmed, payload\.body\)/.test(consoleJs)) {
  throw new Error("preview gate must compare payloads, not remember that a preview happened");
}
if (!/confirmed === JSON\.stringify\(body\)/.test(consoleRules)) {
  throw new Error("previewMatches must compare the serialised bodies");
}
// A refusal is a result. Collapsing it to a status code is what sends an operator to psql.
if (!/error\.reason/.test(consoleJs)) throw new Error("console must render the API's refusal reason verbatim");
if (!/error\.status/.test(consoleJs)) throw new Error("console must show which status the refusal carried");

// The browser's constraints are generated from contracts/openapi.json, which is itself
// drift-gated. A hand-edit here becomes a second copy of the domain rules.
const contract = await read("public/contract.js");
if (!contract.startsWith("// Generated by scripts/generate_web_contract.py")) {
  throw new Error("contract.js is not the generated artefact; run `make web-contract`");
}
if (!consoleRules.includes('import {CONTRACT} from "./contract.js"')) {
  throw new Error("console validation must read the generated contract");
}
if (!contract.includes('"roles"')) {
  throw new Error("the generated contract must carry the role table from policy.py");
}
// Hand-written length rules are the drift. `minLength: 12` typed into a console module
// is a copy of ReviewTransition.note that no gate compares against the model.
for (const [name, source] of [["console.js", consoleJs], ["console_rules.js", consoleRules]]) {
  if (/\b(?:minLength|maxLength)\s*[:=]\s*\d/.test(source)) {
    throw new Error(`${name} carries hand-written length constraints; they belong in the generated contract`);
  }
}
// The role table decides which console a reader is shown, and a hand-written copy of it
// drifts the same way. It must come from the generated contract.
if (/\bROLE_PERMISSIONS\s*=/.test(consoleRules)) {
  throw new Error("console_rules.js carries a hand-copied role table; it belongs in the generated contract");
}
// Showing a console is presentation. If this ever reads as enforcement, the sentence
// that says otherwise is the thing that stops a reviewer believing it.
if (!consoleHtml.includes("Приховування кнопки не є контролем")) {
  throw new Error("the console must state that hiding a control is not access control");
}
// The development proxy must mirror `location /api/` in nginx.conf. It exists because
// the two dev servers could not talk: config.js points at `/api`, the static server had
// no such route, and every request 404'd. The tempting fix — pointing config.js at
// http://127.0.0.1:8000 — "works" only by moving the session cookie cross-origin, which
// is the security property (`credentials: "same-origin"`, `__Host-` prefix), not a
// detail. A prefix that drifts from nginx produces a 404 that reads like a missing route.
const serve = await read("scripts/serve.mjs");
const nginx = await read("nginx.conf");
if (!/const API_PREFIX = "\/api\/";/.test(serve)) {
  throw new Error("the dev server no longer declares the API prefix it proxies");
}
if (!/location \/api\/ \{/.test(nginx)) {
  throw new Error("nginx no longer serves /api/, so the dev proxy mirrors nothing");
}
// nginx's `proxy_pass http://api:8000/` — note the trailing slash — strips the prefix.
// The dev proxy must strip it too, or /api/v1/answers arrives upstream as /api/v1/answers.
if (!/proxy_pass http:\/\/api:8000\/;/.test(nginx)) {
  throw new Error("nginx no longer strips the /api prefix; the dev proxy assumes it does");
}
if (!/API_PREFIX\.length - 1/.test(serve)) {
  throw new Error("the dev proxy no longer strips the prefix nginx strips");
}
// A dev proxy that looks like the production edge is how one ends up serving traffic
// through it. It has no rate limiting, no CSP and no TLS, and it says so on startup.
if (!/development proxy: no rate limit, no CSP, no TLS/.test(serve)) {
  throw new Error("the dev server no longer states that it is not the production edge");
}
// The proxy forwards whatever the client sent. That is acceptable exactly while the
// client can only be this machine, so the bind is loopback and stays loopback.
if (!/const BIND_HOST = "127\.0\.0\.1";/.test(serve) || !/listen\(port, BIND_HOST,/.test(serve)) {
  throw new Error("the dev server no longer binds loopback only");
}
// Hop-by-hop headers are meaningful between two adjacent parties (RFC 9110 §7.6.1).
// Forwarding `connection` or `upgrade` lets a client influence a connection it is not
// party to; forwarding `transfer-encoding` alongside node's own framing is how a
// request gets read twice. nginx strips them, so the stand-in must too.
for (const header of ["connection", "transfer-encoding", "upgrade", "te", "trailer"]) {
  if (!new RegExp(`"${header}"`).test(serve)) {
    throw new Error(`the dev proxy no longer strips the hop-by-hop header ${header}`);
  }
}
if (!/headers: \{ \.\.\.forwardable\(request\.headers\)/.test(serve)) {
  throw new Error("the dev proxy forwards client headers unfiltered");
}

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
function checkAccessibility(page, source) {
  const fail = (message) => { throw new Error(`accessibility [${page}]: ${message}`); };
  const headings = [...source.matchAll(/<h([1-6])[^>]*>/g)].map((m) => Number(m[1]));
  if (headings.filter((level) => level === 1).length !== 1) {
    fail("the page must have exactly one h1");
  }
  for (let index = 1; index < headings.length; index += 1) {
    if (headings[index] - headings[index - 1] > 1) {
      fail(
        `heading level jumps from h${headings[index - 1]} to h${headings[index]}; ` +
          "a screen reader's outline loses the skipped level",
      );
    }
  }
  // Every focusable control needs an accessible name. A button whose label is an icon or
  // whose text is empty is announced as "button", which is not an instruction.
  for (const [, attributes, text] of source.matchAll(/<button([^>]*)>([\s\S]*?)<\/button>/g)) {
    const named = text.replace(/<[^>]*>/g, "").trim().length > 0 ||
      /aria-label=|aria-labelledby=/.test(attributes);
    if (!named) fail(`button without an accessible name: ${attributes}`);
  }
  // Every text input needs a label bound by id. A placeholder disappears on typing and is
  // not announced as a name.
  for (const [, attributes] of source.matchAll(/<(?:input|textarea|select)([^>]*)>/g)) {
    if (/type="(hidden|submit|button)"/.test(attributes)) continue;
    const id = /id="([^"]+)"/.exec(attributes)?.[1];
    if (!id) fail(`form control without an id to label: ${attributes}`);
    if (!source.includes(`for="${id}"`) && !/aria-label=/.test(attributes)) {
      fail(`form control ${id} has no <label for> and no aria-label`);
    }
  }
  for (const [, attributes] of source.matchAll(/<img([^>]*)>/g)) {
    if (!/alt=/.test(attributes)) fail(`image without alt: ${attributes}`);
  }
  if (!/class="skip-link"[^>]*href="#/.test(source)) {
    fail("no skip link, so every navigation costs the header in tab stops");
  }
  if (!/<main[^>]*>/.test(source)) fail("no main landmark");
  // Panels written by script after a response arrives are silent for a screen reader
  // without a live region: the page appears not to have responded.
  const liveRegions = [...source.matchAll(/id="([^"]*result[^"]*)"([^>]*)/g)];
  if (!liveRegions.length) fail("no result region to announce");
  for (const [, id, attributes] of liveRegions) {
    if (!/aria-live="polite"/.test(attributes)) {
      fail(`the ${id} panel is filled by script and must announce itself`);
    }
  }
}

for (const page of PAGES) checkAccessibility(page, await read(page));
console.log(`accessibility validation passed for ${PAGES.length} pages`);
