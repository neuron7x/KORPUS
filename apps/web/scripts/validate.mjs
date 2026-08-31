import { readFile, stat } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { gzipSync } from "node:zlib";
import { fileURLToPath } from "node:url";
import {validateDesignSystem} from "./design_system.mjs";

const asset = (file) => fileURLToPath(new URL(`../${file}`, import.meta.url));
const read = (file) => readFile(asset(file), "utf8");

const DEV_SCRIPTS = ["scripts/serve.mjs", "scripts/build.mjs", "scripts/design_system.mjs", "scripts/generate_design_tokens.mjs", "scripts/build_styles.mjs"];
const SCRIPTS = [
  "public/transport_contract.js", "public/api.js", "public/app.js", "public/chat_fsm.js", "public/routes.js", "public/offline_pack.js", "public/offline_store.js", "public/offline_controller.js", "public/workspace_routes.js", "public/conversations.js", "public/reader_conversations.js",
  "public/reader_corpus.js", "public/reader_declaration.js", "public/reader_verdicts.js", "public/billing.js",
  "public/combat_scene.js", "public/trace.js", "public/decision_field.js",
  "public/console.js", "public/console_accounts.js", "public/console_mutations.js",
  "public/console_readonly.js", "public/console_rules.js", "public/contract.js", "public/sw.js",
];
const PAGES = ["public/index.html", "public/console.html"];
const REQUIRED = [...PAGES, ...SCRIPTS, ...DEV_SCRIPTS, "nginx.conf", "public/tokens.css", "public/styles.css", "public/workspace.css", "public/console.css", "public/manifest.webmanifest", "public/config.js",
  "public/combat.css", "public/decision_field.css", "design/tokens.json", "design/components.json", "design/viewports.json", "design/consumer.css", "design/combat.css", "design/decision_field.css"];

for (const file of REQUIRED) {
  const info = await stat(asset(file));
  if (!info.isFile() || info.size === 0) throw new Error(`invalid web asset: ${file}`);
}

// Performance budget for the consumer shell. This is a deterministic transfer-size
// proxy, not a Lighthouse score: each first-party text asset is gzipped independently,
// matching how the production edge can serve them. The budget prevents a "premium"
// redesign from quietly becoming a framework-sized payload.
const CONSUMER_ENTRY = [
  "public/index.html", "public/tokens.css", "public/styles.css", "public/config.js", "public/transport_contract.js", "public/api.js",
  "public/app.js", "public/chat_fsm.js", "public/conversations.js",
  "public/reader_conversations.js", "public/reader_corpus.js",
  "public/reader_declaration.js", "public/reader_verdicts.js",
];
let consumerGzipBytes = 0;
for (const file of CONSUMER_ENTRY) {
  consumerGzipBytes += gzipSync(await read(file), {level: 9}).byteLength;
}
// 2026-08-31: 32 -> 33 KiB, and the reason belongs beside the number. The shell stood at
// 32 745 bytes, 23 under the cap. Disclosing that a citation begins mid-sentence — the
// case where a span boundary cut "Воєнний об'єкт за|лишається" and the reader was shown a
// permission where the source states a restriction — costs 46 bytes as a warning line and
// 25 as a leading ellipsis. Neither fits. Shaving the disclosure to "⚠ уривок" still
// missed by 6, so the choice was between a cryptic marker and a recorded raise. The
// budget exists so a redesign cannot quietly become framework-sized; one kibibyte spent
// on telling a soldier that the quotation lost its subject is not that, and the next
// person to add a kibibyte has to write their own reason here.
// 2026-08-31 (друге): 33 -> 34 KiB. Оболонка стояла на 33 372, за 420 до стелі.
// Відповідь виводилась одним абзацом — склейкою всіх claim'ів. Питання про днювального
// роти дало чотири: чинна стаття, інший розділ статуту, уривок ЗМІСТУ і текст про
// танкову роту. Присуд по кожному система вже винесла й поклала в payload — третій ніс
// `contested` з причиною «фрагмент верстки, а не речення документа», — і рендер його
// викидав: усі чотири однакові, під заголовком «ПІДСТАВА Є». Розділити твердження,
// назвати джерело кожного і показати вже обчислений присуд коштує 868 байтів: 730 у
// app.js і 138 у стилях. Різати було з чого лише власну прозу, і її вже зрізано на 164;
// решта — сам показ. Бюджет боронить від фреймворка, а не від того, щоб солдат бачив,
// котре з чотирьох речень система сама вважає уривком верстки. Наступний, хто додасть
// кібібайт, пише сюди свою причину.
const CONSUMER_BUDGET_BYTES = 34 * 1024;
if (consumerGzipBytes > CONSUMER_BUDGET_BYTES) {
  throw new Error(
    `consumer shell exceeds ${CONSUMER_BUDGET_BYTES / 1024} KiB gzip budget: ${consumerGzipBytes} bytes`
  );
}
const cssGzipBytes = gzipSync(await read("public/styles.css"), {level: 9}).byteLength;
const tokenCssGzipBytes = gzipSync(await read("public/tokens.css"), {level: 9}).byteLength;
// 2026-08-31: 9 -> 10 KiB, з тієї самої причини, що й оболонка вище, і число теж
// належить поруч. CSS стояв на 9 199 при стелі 9 216 — сімнадцять байтів. Показ присуду
// на кожному твердженні коштує 67: смуга зліва, два кольори на неї і знятий типовий
// відступ абзаца. Спроба вписатися в сімнадцять — приклеїти `.claim .meta` до наявного
// `.citation .meta` — зекономила СІМ: gzip уже стискав цей повтор, а селектори стали
// довшими. Тобто вибір був не «економно чи ні», а «показувати чи ні». Сімнадцять
// байтів — це не бюджет, це його відсутність; піднімаю на кібібайт, щоб наступна
// потрібна дрібниця не впиралася в округлення.
const CSS_BUDGET_BYTES = 10 * 1024;
if (cssGzipBytes + tokenCssGzipBytes > CSS_BUDGET_BYTES) {
  throw new Error(
    `consumer CSS exceeds ${CSS_BUDGET_BYTES / 1024} KiB gzip budget: ${cssGzipBytes + tokenCssGzipBytes} bytes`
  );
}
console.log(`consumer transfer budget passed: ${consumerGzipBytes} gzip bytes`);
const appSourceForBudget = await read("public/app.js");
for (const lazy of ["./billing.js", "./workspace_routes.js"]) {
  if (!appSourceForBudget.includes(`import("${lazy}")`)) {
    throw new Error(`${lazy} must remain lazy-loaded; eager loading breaks the initial-shell budget`);
  }
}
const designSystem = await validateDesignSystem();
console.log(`design system passed: ${designSystem.tokenCount} tokens / ${designSystem.componentCount} component contracts`);

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
if (/id="conversations"[^>]*\sopen(?:\s|>)/.test(html)) {
  throw new Error("mobile conversation disclosure must not ship forced open; desktop opens it at boot");
}

// ---------------------------------------------------------------- security contract
//
// The consoles (WEB-001) added a second page. Two pages meant two chances to hand-roll
// auth, and the second copy is where a token reaches localStorage or a POST goes out
// without its CSRF header. So the contract moved: api.js is the only module allowed to
// touch credentials or the network, and every other script is checked for *absence*.
const api = await read("public/api.js");
const transportContract = await read("public/transport_contract.js");
const routesSource = await read("public/routes.js");
const runtimeConfig = await read("public/config.js");
if (!transportContract.includes('"/v1/client/bootstrap"')) throw new Error("transport contract lacks client bootstrap");
if (!api.includes('from "./transport_contract.js"')) throw new Error("api.js must consume generated transport contract");
if (!api.includes('assertTransportRoute(path, method)')) throw new Error("network calls must be checked against the transport contract");
if (runtimeConfig.includes("clientVersion")) throw new Error("client release identity must not be duplicated in config.js");
for (const marker of ["effective_permissions", "offline_pack_enabled", "audit:read", "document:list", "answer:read"]) {
  if (!routesSource.includes(marker)) throw new Error(`server-projected route policy missing: ${marker}`);
}
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
const consoleAccounts = await read("public/console_accounts.js");
const consoleMutations = await read("public/console_mutations.js");
const consoleReadonly = await read("public/console_readonly.js");
const consoleRules = await read("public/console_rules.js");
const conversationsJs = await read("public/conversations.js");
const readerConversations = await read("public/reader_conversations.js");
const readerCorpus = await read("public/reader_corpus.js");
const readerDeclaration = await read("public/reader_declaration.js");
const readerVerdicts = await read("public/reader_verdicts.js");
const billingJs = await read("public/billing.js");
const workspaceRoutes = await read("public/workspace_routes.js");
const offlineController = await read("public/offline_controller.js");
const browserLogic = [app, conversationsJs, readerConversations, readerCorpus, readerDeclaration, readerVerdicts, billingJs].join("\n");
const networkModules = [
  ["app.js", app], ["console.js", consoleJs], ["console_accounts.js", consoleAccounts],
  ["console_mutations.js", consoleMutations], ["console_readonly.js", consoleReadonly],
  ["conversations.js", conversationsJs], ["workspace_routes.js", workspaceRoutes], ["offline_controller.js", offlineController], ["reader_conversations.js", readerConversations],
  ["reader_corpus.js", readerCorpus], ["billing.js", billingJs],
];
for (const [name, source] of networkModules) {
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
for (const [name, source] of [
  ["reader_declaration.js", readerDeclaration], ["reader_verdicts.js", readerVerdicts],
]) {
  if (/\bfetch\s*\(/.test(source) || /document\.cookie/.test(source)) {
    throw new Error(`${name} crosses the reader module boundary into network/session transport`);
  }
}
// localStorage only, not sessionStorage. The rule is that nothing about a session may
// outlive the tab: localStorage does (a token there survives the browser closing and the
// next person opening it), sessionStorage does not (it is cleared when the tab closes).
// app.js deliberately mirrors the declaration into sessionStorage so a reload does not
// cost a soldier three fields — and that survives the tab, not the shift. Matches use,
// not mention, so a comment naming the hazard does not trip its own guard.
const PERSISTENT_STORAGE = /localStorage\s*[.[;)=,]/;
for (const file of [
  "public/transport_contract.js", "public/api.js", "public/app.js", "public/chat_fsm.js", "public/routes.js", "public/offline_pack.js", "public/offline_store.js", "public/offline_controller.js", "public/workspace_routes.js", "public/conversations.js", "public/reader_conversations.js",
  "public/reader_corpus.js", "public/reader_declaration.js", "public/reader_verdicts.js", "public/billing.js",
  "public/console.js", "public/console_accounts.js", "public/console_mutations.js",
  "public/console_readonly.js", "public/console_rules.js",
]) {
  if (PERSISTENT_STORAGE.test(await read(file))) {
    throw new Error(`persistent token storage detected in ${file}`);
  }
}
// A declaration mirrored to sessionStorage must be re-validated on the way back in, never
// trusted: a tampered value must not enter the audit chain as somebody's declaration. The
// check reads the restore function's own body, not the mere presence of its name — a
// trusting `return JSON.parse(...)` must fail even while the function still exists.
if (/sessionStorage/.test(readerDeclaration)) {
  const restore = readerDeclaration.match(/function restoreDeclaration\(\)[\s\S]*?\n\}/);
  if (!restore) {
    throw new Error("sessionStorage is used but no restoreDeclaration function validates it");
  }
  if (!/\.every\(/.test(restore[0]) || !/\.trim\(\)/.test(restore[0])) {
    throw new Error("a restored declaration is trusted without re-validation");
  }
}

// ---------------------------------------------------------------- offline shell
//
// The service worker promises an offline shell. One static import missing from its cache
// makes a module fail to execute offline, which turns a degraded page into a blank one —
// the exact failure /conversations.js caused before it was added. So every module app.js
// or api.js statically imports must be in the SW's ASSETS list.
const sw = await read("public/sw.js");
const assetsMatch = sw.match(/const ASSETS = \[([^\]]*)\]/);
if (!assetsMatch) throw new Error("the service worker no longer declares an ASSETS list");
const cached = new Set(
  [...assetsMatch[1].matchAll(/"([^"]+)"/g)].map(m => m[1]),
);
if (!cached.has("/workspace.css")) {
  throw new Error("lazy workspace stylesheet is not cached for offline deep links");
}
const moduleQueue = ["public/app.js", "public/api.js"];
const visitedModules = new Set();
while (moduleQueue.length) {
  const file = moduleQueue.shift();
  if (visitedModules.has(file)) continue;
  visitedModules.add(file);
  const source = await read(file);
  for (const [, spec] of source.matchAll(/from "(\.\/[^"]+)"/g)) {
    const asset = spec.replace(/^\.\//, "/");
    if (!cached.has(asset)) {
      throw new Error(`${file} imports ${asset}, which the service worker does not cache — the offline shell would be blank`);
    }
    moduleQueue.push(`public/${asset.slice(1)}`);
  }
}
// A network failure must be told apart from a refusal: the question was never asked, so
// nothing was decided about the corpus, and the message says "no signal", not "no basis".
if (!/class NetworkError/.test(api) || !/AbortSignal\.timeout/.test(api)) {
  throw new Error("requests have no timeout or no offline signal — a dead uplink hangs the button");
}
if (!/НЕМАЄ ЗВ’ЯЗКУ/.test(api)) {
  throw new Error("a lost link is rendered as a generic error, not as a lost link");
}

// ---------------------------------------------------------------- checkout CSP
//
// The browser posts LiqPay checkout fields directly to the payment provider. That route
// must be intentionally allowed by CSP, but no wildcard form destination may be accepted.
const nginx = await read("nginx.conf");
const cspHeaders = [...nginx.matchAll(/Content-Security-Policy "([^"]+)"/g)].map((match) => match[1]);
if (cspHeaders.length === 0) throw new Error("nginx declares no Content-Security-Policy");
if (!/add_header Strict-Transport-Security "max-age=31536000" always;/.test(nginx)) {
  throw new Error("nginx declares no HSTS policy");
}
for (const csp of cspHeaders) {
  if (!csp.includes("form-action 'self' https://www.liqpay.ua;")) {
    throw new Error("checkout CSP must allow only self and the exact LiqPay form endpoint origin");
  }
  if (/form-action[^;]*\*/.test(csp)) {
    throw new Error("checkout CSP must never use a wildcard form destination");
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
// Matched on the invariant, not on the expression that satisfied it: the first version
// pinned `query.value` verbatim and failed the moment the question was read into a
// variable first — a rename it had no business having an opinion about, while a change
// that actually dropped `declaration` would have been the same one line.
// Matched on the object literal rather than on `body:`, after ACT-001 gave the question
// two destinations — `/v1/answers` and `/v1/conversations/{id}/ask` — and the body became
// a variable built once and sent to whichever applies. Pinning the call site again would
// mean re-editing this line every time a third destination appears, which is how a gate
// ends up describing the code instead of the rule.
if (!/\{\s*text:[^{}]*,\s*declaration\s*\}/.test(app)) {
  throw new Error("the declaration no longer travels with the query");
}

// ---------------------------------------------------------------- chat interaction
//
// The consumer surface is a chat. Plain Enter submits and Shift+Enter creates a newline;
// IME composition must never accidentally submit. This is a user-facing interaction
// contract, not a keyboard shortcut preference.
if (!/event\.key === "Enter" && !event\.shiftKey && !event\.isComposing/.test(app) ||
    !/queryForm\.requestSubmit\(\)/.test(app)) {
  throw new Error("composer no longer submits on plain Enter while preserving Shift+Enter/IME");
}
if (!/Enter — надіслати · Shift \+ Enter — новий рядок/.test(html)) {
  throw new Error("composer help text no longer describes the actual Enter behavior");
}
if (!/function resizeComposer\(\)/.test(app) || !/Math\.min\(query\.scrollHeight, 190\)/.test(app)) {
  throw new Error("composer no longer auto-sizes within its bounded height");
}

// Optional inference must be visible as assistance, never presented as the source of truth.
// The status comes from the server because provider configuration is an operator decision;
// the browser may display it but must not infer it from client configuration.
if (!/id="inference-state"[^>]*role="status"/.test(html) ||
    !/id="inference-detail"/.test(html) ||
    !/call\("\/v1\/inference\/status"\)/.test(app) ||
    !/max_input_bytes/.test(app) || !/max_response_bytes/.test(app)) {
  throw new Error("inference assistance status is no longer server-derived and visible");
}
if (!/Модель може допомагати шукати й компонувати, але не створює факти/.test(html)) {
  throw new Error("inference surface no longer says the model is not factual authority");
}

// ---------------------------------------------------------------- conversations
//
// History is context, never a source. The surface has to keep saying so, because the one
// thing an interface can do that the API cannot prevent is prepend the transcript to the
// next question — and the result is a system citing itself with a citation list that looks
// complete.
if (!/Історія — це контекст, не доказ/.test(html)) {
  throw new Error("the conversation panel no longer says history is not evidence");
}
if (/askIn\([^)]*transcript|messages\s*\.\s*map[^;]*body/.test(browserLogic)) {
  throw new Error("the transcript is being sent with a question");
}
// A stored turn is marked as stored. Rendering history identically to a live answer claims
// citation cards that are not being shown.
if (!/"turn stored"/.test(readerConversations) || !/\.turn\.stored \{/.test(await read("public/styles.css"))) {
  throw new Error("a turn read back from storage is indistinguishable from a live answer");
}
// 402 is not a statement about the corpus. Rendering it as ПІДСТАВИ НЕМАЄ tells a reader
// the manuals are silent on a question they were simply not shown.
if (!/ПОТРІБНА ПІДПИСКА/.test(app)) {
  throw new Error("a payment refusal is rendered as an evidence refusal");
}
// A refusal read back from history is still a refusal. Found in a browser: the stored turn
// rendered as a paragraph of prose identical in shape to an answer, so a reader skimming
// their own transcript would have counted "недостатньо доказів" as something the corpus
// said. The verdict now travels with the message and is rendered as a verdict.
if (!/message\.answer_status/.test(readerConversations) || !/ВЕРДИКТ НЕ ЗАПИСАНО/.test(readerConversations)) {
  throw new Error("a stored refusal is rendered without its verdict");
}
// A truncated list says so. The corpus panel already names what it cut ("…і ще N"); the
// conversation list stopped at fifty and said nothing, which a reader takes as fifty being
// all they have. A transcript is worse: it is read oldest-first, so what a cut removes is
// the most recent turns — the ones somebody came back for.
if (!/page\.has_more/.test(readerConversations) || !/Показати більше/.test(conversationsJs)) {
  throw new Error("a truncated conversation list does not say it was truncated");
}
if (!/Пізніші не показані/.test(readerConversations)) {
  throw new Error("a truncated transcript does not say its newest turns are missing");
}
// The client never names an account. A request that could would be a client choosing whose
// history to read, which is the whole of a broken-object-level-authorization bug.
if (/account_id/.test(browserLogic)) {
  throw new Error("the browser names an account; ownership is the server's to decide");
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
if (!/ПІДСТАВИ НЕМАЄ/.test(readerVerdicts)) {
  throw new Error("the withheld verdict no longer has its own wording");
}

// RAG-019: retrieval_score is a ranking utility, not a calibrated probability. The UI
// renders it as a number, so the sentence that says what it is not must travel with it.
if (!app.includes("Якість ранжування не є ймовірністю правильності")) throw new Error("uncalibrated score disclaimer missing");
if (app.includes("retrieval_score") && !app.includes("Якість ранжування")) throw new Error("score rendered without its non-probability label");

const manifest = JSON.parse(await read("public/manifest.webmanifest"));
if (!manifest.name || !manifest.start_url || manifest.display !== "standalone") throw new Error("PWA manifest contract failed");

// ---------------------------------------------------------------- console contract
//
// WEB-001's acceptance predicate is that every critical workflow runs without raw DB or
// API manipulation. Reaching it needs more than the forms existing.
const consoleHtml = await read("public/console.html");
for (const id of [
  "console-curator", "console-reviewer", "console-corpus", "console-auditor",
  "console-accounts",
  "ingest-form", "review-form", "rescind-form", "audit-events-form",
  "account-find-form", "account-status-form",
]) {
  if (!consoleHtml.includes(`id="${id}"`)) throw new Error(`operator console missing surface: ${id}`);
}
// Nothing irreversible fires on a first click. Each of the three writing workflows has a
// preview button and a submit that ships disabled.
// `account` joined the list in v6.1.0: switching a person off is irreversible in the way
// that matters — they lose access immediately — and the operator doing it has been woken
// up. It gets the same preview-then-submit gate as ingesting or rescinding.
for (const workflow of ["ingest", "review", "rescind", "account"]) {
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
if (!/const API_PREFIX = "\/api\/";/.test(serve)) {
  throw new Error("the dev server no longer declares the API prefix it proxies");
}
if (!/location \/api\/ \{/.test(nginx)) {
  throw new Error("nginx no longer serves /api/, so the dev proxy mirrors nothing");
}
// nginx `add_header` REPLACES the inherited set rather than merging with it, so a
// location that adds one header of its own drops every header declared above it.
// Measured 2026-08-06 against the real edge: `curl -I /` returned no
// Content-Security-Policy, because `location = /index.html` sets Cache-Control. Every
// page and asset the browser loads was served without CSP, without X-Frame-Options and
// without nosniff — and the whole no-framework, self-only design rests on that CSP.
//
// There is no merge directive in stock nginx, so the set is repeated per location. This
// asserts the repetition: any block that sets a header must also set the CSP.
{
  const blocks = [...nginx.matchAll(/location[^{]*\{([^{}]*)\}/g)].map((match) => match[1]);
  const carrying = blocks.filter((body) => /add_header/.test(body));
  if (carrying.length < 4) {
    throw new Error("fewer location blocks set headers than expected; this check is stale");
  }
  for (const body of carrying) {
    if (!/add_header Content-Security-Policy/.test(body)) {
      throw new Error(
        "a location sets add_header without repeating the Content-Security-Policy; " +
          "nginx replaces the inherited set, so that location serves no CSP at all",
      );
    }
    for (const header of ["X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy", "Strict-Transport-Security"]) {
      if (!new RegExp(`add_header ${header}`).test(body)) {
        throw new Error(`a location that sets headers does not repeat ${header}`);
      }
    }
  }
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
// WCAG 2.2 §1.4.3 AA over the colour tokens, computed rather than asserted in a comment.
//
// The palette carried a sentence saying contrast "is checked, not estimated" and listing
// --text, --muted and --accent. --muted-2 was not in the list and was 3.59:1 on
// --surface-2 — the colour of every hint under the identity fields. A claim that names
// the tokens it checked is not a claim about the ones it did not, and a comment cannot
// tell the difference. This can.
const relative = (component) => {
  const c = component / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};
const luminance = (hex) => {
  const [r, g, b] = [1, 3, 5].map((index) => parseInt(hex.slice(index, index + 2), 16));
  return 0.2126 * relative(r) + 0.7152 * relative(g) + 0.0722 * relative(b);
};
const contrast = (a, b) => {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
};

{
  const tokenCss = await read("public/tokens.css");
  const consumerCss = await read("public/styles.css");
  if (/:root\s*\{/.test(consumerCss)) {
    throw new Error("accessibility: consumer stylesheet shadows canonical design tokens with :root");
  }
  const blocks = [...tokenCss.matchAll(/:root\s*\{([^}]*)\}/g)];
  if (blocks.length !== 1) {
    throw new Error(`accessibility: expected exactly one generated :root token block, found ${blocks.length}`);
  }
  const active = blocks[0][1];
  const token = (name) => /^#[0-9a-f]{6}$/i.test(
    new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`).exec(active)?.[1] ?? "",
  ) ? new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`).exec(active)[1] : null;

  const surfaces = ["bg", "surface", "surface-2"].map(token).filter(Boolean);
  if (surfaces.length === 0) throw new Error("accessibility: no surface tokens to check against");
  for (const name of ["text", "muted", "muted-2"]) {
    const colour = token(name);
    if (!colour) throw new Error(`accessibility: palette has no --${name} to check`);
    for (const surface of surfaces) {
      const ratio = contrast(colour, surface);
      if (ratio < 4.5) {
        throw new Error(
          `accessibility: --${name} (${colour}) on ${surface} is ${ratio.toFixed(2)}:1, ` +
          "below WCAG 2.2 AA \u00a71.4.3 (4.5:1) for body text",
        );
      }
    }
  }
  console.log(`contrast validated for ${surfaces.length} surfaces`);

  // ZBIM: субстрат — нульовий вузол, а не «дуже темний фон».
  //
  // `--bg` був `#010101`: відносна яскравість 0.000304, тобто НЕ нуль. Різниця
  // непомітна оку й помітна контракту — субстрат або є абсолютним нулем sRGB, або є
  // просто ще однією поверхнею, і тоді вся ієрархія втрачає нижній якір.
  //
  // Це твердження про СИГНАЛ, не про яскравість: скільки cd/m² видасть конкретний
  // дисплей, звідси не випливає й тут не заявляється. Фізичний чорний залежить від
  // панелі, tone mapping і освітлення кімнати; CSS керує лише кодом.
  const substrate = token("bg");
  if (substrate?.toLowerCase() !== "#000000") {
    throw new Error(
      `zero-black: substrate --bg is ${substrate}, not #000000 — ` +
      "the zero node of the palette must be the sRGB zero itself",
    );
  }

  // Ненавмисне освітлення субстрату. Градієнт, прозорість чи фільтр на `html`/`body`
  // піднімають нуль, і жодна перевірка токенів цього не побачить: токен лишається
  // чорним, а екран — ні. Тут стояв `radial-gradient` на rgba(217,255,104,.055).
  const consumer = await read("design/consumer.css");
  // Група 3, не 1. Перша версія брала `body` з деструктуризації — а це група `(^|})`,
  // тобто порожній рядок: правило не могло почервоніти НІКОЛИ. Спіймано власним
  // негативним контролем, не читанням; сам гейт про сліпоту гейтів був сліпий.
  for (const match of consumer.matchAll(/(^|\})\s*(html|body)\s*\{([^}]*)\}/gm)) {
    const rule = match[3] ?? "";
    for (const [property, pattern] of [
      ["gradient", /gradient\(/],
      ["opacity", /(^|;)\s*opacity\s*:/],
      ["filter", /(^|;)\s*(backdrop-)?filter\s*:/],
      ["blend", /mix-blend-mode\s*:/],
    ]) {
      if (pattern.test(rule)) {
        throw new Error(
          `zero-black: the substrate rule carries ${property} — ` +
          "the zero node must not be lit by accident",
        );
      }
    }
  }
  console.log("zero-black substrate validated: #000000, unlit");
}

console.log(`accessibility validation passed for ${PAGES.length} pages`);
