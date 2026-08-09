// Negative controls for the web gate itself.
//
// `node scripts/validate.mjs` printing "passed" is evidence only if it is capable of
// printing anything else. Two of its checks were inert before this file existed: the
// syntax check exited 0 for every module because `node --check` gives up silently on an
// `import`, and the persistent-storage scan matched its own comment. Neither was visible
// from a green run.
//
// So each mutation below removes exactly one control from a copy of the tree and asserts
// the validator refuses. A mutation that survives is a check that was never checking.

import test from "node:test";
import assert from "node:assert/strict";
import { cp, mkdtemp, readFile, writeFile, rm } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = dirname(dirname(fileURLToPath(import.meta.url)));

async function runWith(mutate) {
  const root = await mkdtemp(join(tmpdir(), "korpus-web-gate-"));
  try {
    await cp(join(WEB, "public"), join(root, "public"), {recursive: true});
    await cp(join(WEB, "scripts"), join(root, "scripts"), {recursive: true});
    await cp(join(WEB, "design"), join(root, "design"), {recursive: true});
    await cp(join(WEB, "nginx.conf"), join(root, "nginx.conf"));
    const edit = async (file, transform) => {
      const path = join(root, file);
      await writeFile(path, transform(await readFile(path, "utf8")), "utf8");
    };
    await mutate(edit, root);
    const result = spawnSync(process.execPath, [join(root, "scripts/validate.mjs")], {
      encoding: "utf8",
    });
    return {status: result.status, output: `${result.stdout}${result.stderr}`};
  } finally {
    await rm(root, {recursive: true, force: true});
  }
}

test("the unmutated tree passes, so a failure below means the mutation", async () => {
  const {status} = await runWith(async () => {});
  assert.equal(status, 0);
});

test("a syntax error in a module is caught", async () => {
  // The control that was inert: `node --check` returns 0 for any file with an import.
  const {status, output} = await runWith(edit =>
    edit("public/console.js", source => `${source}\nconst broken = ;\n`));
  assert.notEqual(status, 0);
  assert.match(output, /syntax check failed for public\/console\.js/);
});

test("a token written to persistent storage is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/api.js", source => `${source}\nlocalStorage.setItem("t", bearerToken);\n`));
  assert.notEqual(status, 0);
  assert.match(output, /persistent token storage detected/);
});

test("a bare localStorage reference is caught (sessionStorage is now allowed)", async () => {
  // localStorage outlives the tab and is forbidden everywhere; sessionStorage is cleared
  // when the tab closes and is permitted for the declaration alone.
  const caught = await runWith(edit =>
    edit("public/console.js", source => `${source}\nconst store = localStorage;\n`));
  assert.notEqual(caught.status, 0);
  const allowed = await runWith(edit =>
    edit("public/console.js", source => `${source}\nconst store = sessionStorage;\n`));
  assert.equal(allowed.status, 0, "sessionStorage in a console is no longer a violation");
});

test("a console calling fetch behind api.js is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/console.js", source => `${source}\nawait fetch("/api/v1/documents");\n`));
  assert.notEqual(status, 0);
  assert.match(output, /calls fetch directly/);
});

test("a console reading cookies directly is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/console.js", source => `${source}\nconst c = document.cookie;\n`));
  assert.notEqual(status, 0);
  assert.match(output, /reads cookies directly/);
});

test("dropping the CSRF header from state-changing requests is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/api.js", source =>
      source.replace('!["GET", "HEAD", "OPTIONS"].includes(method)', "false")));
  assert.notEqual(status, 0);
  assert.match(output, /CSRF header must be attached by method/);
});

test("a submit button that ships enabled is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/console.html", source =>
      source.replace('id="review-submit" type="submit" disabled', 'id="review-submit" type="submit"')));
  assert.notEqual(status, 0);
  assert.match(output, /review submit is enabled before anything was previewed/);
});

test("removing a preview button is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/console.html", source => source.replace('id="ingest-preview"', 'id="ingest-nothing"')));
  assert.notEqual(status, 0);
  assert.match(output, /ingest has no preview/);
});

test("weakening the preview gate to a boolean is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/console.js", source =>
      source.replace("!previewMatches(confirmed, payload.body)", "confirmed === null")));
  assert.notEqual(status, 0);
  assert.match(output, /preview gate must compare payloads/);
});

test("swallowing the refusal reason is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/console.js", source => source.replaceAll("error.reason", '"помилка"')));
  assert.notEqual(status, 0);
  assert.match(output, /refusal reason verbatim/);
});

test("a hand-written length constraint in the console is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/console_rules.js", source => `${source}\nconst NOTE = {minLength: 12};\n`));
  assert.notEqual(status, 0);
  assert.match(output, /hand-written length constraints/);
});

test("a hand-copied role table is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/console_rules.js", source =>
      `${source}\nconst ROLE_PERMISSIONS = {curator: ["document:ingest"]};\n`));
  assert.notEqual(status, 0);
  assert.match(output, /hand-copied role table/);
});

test("a hand-edited contract.js is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/contract.js", source => source.replace(/^\/\/ Generated by[^\n]*\n/, "")));
  assert.notEqual(status, 0);
  assert.match(output, /not the generated artefact/);
});

test("a form control losing its label is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/console.html", source =>
      source.replace('<label for="review-note">Обґрунтування, що входить до аудиту</label>', "")));
  assert.notEqual(status, 0);
  assert.match(output, /review-note has no <label for>/);
});

test("a second h1 on the console page is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/console.html", source =>
      source.replace("<h2>Куратор · внесення джерела</h2>", "<h1>Куратор · внесення джерела</h1>")));
  assert.notEqual(status, 0);
  assert.match(output, /accessibility \[public\/console\.html\]/);
});

test("a result panel that cannot announce itself is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/console.html", source =>
      source.replace('id="review-result" class="outcome" role="status" aria-live="polite"',
        'id="review-result" class="outcome"')));
  assert.notEqual(status, 0);
  assert.match(output, /review-result panel is filled by script/);
});

test("removing the statement that hiding is not access control is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/console.html", source =>
      source.replace("Приховування кнопки не є контролем", "Кнопки приховано")));
  assert.notEqual(status, 0);
  assert.match(output, /hiding a control is not access control/);
});

test("removing the uncalibrated-score disclaimer is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/app.js", source =>
      source.replace("Ranking utility не є ймовірністю правильності", "Оцінка")));
  assert.notEqual(status, 0);
  assert.match(output, /uncalibrated score disclaimer missing/);
});

test("an empty asset is caught", async () => {
  const {status, output} = await runWith(edit => edit("public/console_rules.js", () => ""));
  assert.notEqual(status, 0);
  assert.match(output, /invalid web asset/);
});

test("a dev proxy that stops stripping the prefix nginx strips is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("scripts/serve.mjs", source => source.replace("API_PREFIX.length - 1", "0")));
  assert.notEqual(status, 0);
  assert.match(output, /no longer strips the prefix nginx strips/);
});

test("a dev proxy whose prefix drifts from nginx is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("scripts/serve.mjs", source =>
      source.replace('const API_PREFIX = "/api/";', 'const API_PREFIX = "/backend/";')));
  assert.notEqual(status, 0);
  assert.match(output, /no longer declares the API prefix/);
});

test("dropping nginx's prefix strip is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("nginx.conf", source =>
      source.replace("proxy_pass http://api:8000/;", "proxy_pass http://api:8000;")));
  assert.notEqual(status, 0);
  assert.match(output, /no longer strips the \/api prefix/);
});

test("a dev server that stops saying it is not the production edge is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("scripts/serve.mjs", source =>
      source.replace("development proxy: no rate limit, no CSP, no TLS", "ready")));
  assert.notEqual(status, 0);
  assert.match(output, /not the production edge/);
});

test("a syntax error in the dev server is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("scripts/serve.mjs", source => `${source}\nconst broken = ;\n`));
  assert.notEqual(status, 0);
  assert.match(output, /syntax check failed for scripts\/serve\.mjs/);
});

test("a tab without its panel is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/console.html", source =>
      source.replace('<section id="console-auditor"', '<section id="console-audit"')));
  assert.notEqual(status, 0);
  assert.match(output, /operator console missing surface: console-auditor/);
});

test("a dev proxy that stops stripping hop-by-hop headers is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("scripts/serve.mjs", source =>
      source.replace("headers: { ...forwardable(request.headers)", "headers: { ...request.headers")));
  assert.notEqual(status, 0);
  assert.match(output, /forwards client headers unfiltered/);
});

test("a dev proxy that stops binding loopback is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("scripts/serve.mjs", source =>
      source.replace('const BIND_HOST = "127.0.0.1";', 'const BIND_HOST = "0.0.0.0";')));
  assert.notEqual(status, 0);
  assert.match(output, /no longer binds loopback only/);
});

test("merging the verified and declared identities is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/index.html", source =>
      source.replace('class="chip declared"', 'class="chip verified"')));
  assert.notEqual(status, 0);
  assert.match(output, /no longer distinguishes verified from declared/);
});

test("styling a declared attribute like a verified one is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/styles.css", source =>
      source.replace(".chip.declared { border-style: dashed; color: var(--muted-2); background: transparent; }",
                     ".chip.declared { color: var(--accent); }")));
  assert.notEqual(status, 0);
  assert.match(output, /styled like a verified one/);
});

test("dropping the declaration from the query is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/app.js", source =>
      source.replace("const body = {text: question, declaration};",
                     "const body = {text: question};")));
  assert.notEqual(status, 0);
  assert.match(output, /no longer travels with the query/);
});

test("the negative control above still edits something", async () => {
  // The control failed silently once already: it replaced a literal that ACT-001 had
  // rewritten, so the mutation was a no-op and the gate passed for the right reason
  // against the wrong tree. A control whose edit does nothing is a control that passes
  // for ever.
  const {readFile} = await import("node:fs/promises");
  const source = await readFile(new URL("../public/app.js", import.meta.url), "utf8");
  assert.ok(
    source.includes("const body = {text: question, declaration};"),
    "the declaration-drop control no longer names anything in app.js",
  );
});

test("renaming the question variable is not caught", async () => {
  // The dual of the test above. The gate is about `declaration` reaching the audit
  // chain; it had an opinion about what the question was called, so reading the value
  // into a variable before posting it failed a check that guards something else.
  const {status} = await runWith(edit =>
    edit("public/app.js", source =>
      source.replace("const body = {text: question, declaration};",
                     "const body = {text: asked, declaration};")
            .replace("const question = query.value.trim();", "const asked = query.value.trim();")
            .replaceAll("render(answer, question);", "render(answer, asked);")
            .replaceAll("escapeHtml(question)}", "escapeHtml(asked)}")));
  assert.equal(status, 0);
});

test("a consumer shell that blows the transfer budget is caught", async () => {
  const payload = Array.from({length: 7000}, (_, index) => `.budget-${index}{--n:${index}px}`).join("\n");
  const {status, output} = await runWith(edit =>
    edit("public/styles.css", source => `${source}\n${payload}\n`));
  assert.notEqual(status, 0);
  assert.match(output, /exceeds (32|8) KiB gzip budget/);
});

test("turning plain Enter into a newline-only composer is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/app.js", source =>
      source.replace('event.key === "Enter" && !event.shiftKey && !event.isComposing',
                     'event.key === "Enter" && event.shiftKey && !event.isComposing')));
  assert.notEqual(status, 0);
  assert.match(output, /composer no longer submits on plain Enter/);
});

test("an error summary that does not take focus is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/app.js", source => source.replace("errors.focus();", "")));
  assert.notEqual(status, 0);
  assert.match(output, /does not move focus/);
});

test("a hidden section that a display rule can override is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/styles.css", source =>
      source.replace("[hidden] { display: none !important; }", "")));
  assert.notEqual(status, 0);
  assert.match(output, /can be overridden by a display rule/);
});

test("a location that sets a header without repeating the CSP is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("nginx.conf", source =>
      source.replace(
        /location = \/config\.js \{[\s\S]*?\n    \}/,
        'location = /config.js { add_header Cache-Control "no-store" always; }')));
  assert.notEqual(status, 0);
  assert.match(output, /serves no CSP at all/);
});

test("a colour token below AA contrast is caught", async () => {
  const {status, output} = await runWith(async edit => {
    await edit("design/tokens.json", source => source.replace('"hex": "#959f96"', '"hex": "#4f564f"'));
    await edit("public/tokens.css", source => source.replace("--muted-2: #959f96;", "--muted-2: #4f564f;"));
  });
  assert.notEqual(status, 0);
  assert.match(output, /below WCAG 2\.2 AA/);
});

test("introducing a second palette root is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/styles.css", source =>
      `${source}\n:root { --muted-2: #6d7365; }\n`));
  assert.notEqual(status, 0);
  assert.match(output, /shadows canonical design tokens with :root/);
});

test("design token drift is caught before CSS can silently diverge", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/tokens.css", source => source.replace("--accent: #d9ff68;", "--accent: #ffffff;")));
  assert.notEqual(status, 0);
  assert.match(output, /design tokens drift/);
});

test("mobile conversation history no longer ships forced open", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/index.html", source => source.replace('id="conversations" class="conversations" hidden', 'id="conversations" class="conversations" hidden open')));
  assert.notEqual(status, 0);
  assert.match(output, /mobile conversation disclosure/);
});

// ---------------------------------------------------------------- ACT-001 controls
//
// Four checks arrived with the conversation surface. Each is inert until something proves
// it can fail, and the one that would matter most — a transcript being sent back as
// evidence — is exactly the kind of change that looks like an improvement in review.

test("removing the sentence that history is not evidence is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/index.html", source =>
      source.replace("Історія — це контекст, не доказ.", "Історія розмов.")));
  assert.notEqual(status, 0);
  assert.match(output, /no longer says history is not evidence/);
});

test("rendering a stored turn like a live one is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/reader_conversations.js", source =>
      source.replace('block.className = "turn stored";', 'block.className = "turn";')));
  assert.notEqual(status, 0);
  assert.match(output, /indistinguishable from a live answer/);
});

test("dropping the stored-turn styling is caught even when the class stays", async () => {
  // The class alone changes nothing a reader can see. Both halves are the control.
  const {status, output} = await runWith(edit =>
    edit("public/styles.css", source =>
      source.replace(".turn.stored {", ".turn.was-stored {")));
  assert.notEqual(status, 0);
  assert.match(output, /indistinguishable from a live answer/);
});

test("rendering a payment refusal as an evidence refusal is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/app.js", source =>
      source.replace('"ПОТРІБНА ПІДПИСКА"', '"ПІДСТАВИ НЕМАЄ"')));
  assert.notEqual(status, 0);
  assert.match(output, /payment refusal is rendered as an evidence refusal/);
});

test("a browser that names an account is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/conversations.js", source =>
      `${source}\nexport const forAccount = account_id => account_id;\n`));
  assert.notEqual(status, 0);
  assert.match(output, /names an account/);
});

test("a fetch call added to the conversation module is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/conversations.js", source =>
      `${source}\nexport const sneak = () => fetch("/v1/conversations");\n`));
  assert.notEqual(status, 0);
  assert.match(output, /calls fetch directly/);
});

test("a stored refusal rendered without its verdict is caught", async () => {
  // The defect this control exists for was found by reading a transcript in a browser,
  // not by a test: history rendered "недостатньо доказів" in the same shape as an answer.
  const {status, output} = await runWith(edit =>
    edit("public/reader_conversations.js", source =>
      source.replace("? VERDICT[message.answer_status] ?? [\"ВІДМОВА\", \"withheld\"]",
                     "? [\"\", \"withheld\"]")
            .replace('["ВЕРДИКТ НЕ ЗАПИСАНО", "withheld"]', '["", "withheld"]')));
  assert.notEqual(status, 0);
  assert.match(output, /stored refusal is rendered without its verdict/);
});

test("a conversation list truncated in silence is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/reader_conversations.js", source => source.replaceAll("page.has_more", "false")));
  assert.notEqual(status, 0);
  assert.match(output, /does not say it was truncated/);
});

test("a transcript that hides its newest turns in silence is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/reader_conversations.js", source =>
      source.replace("Пізніші не показані.", "")));
  assert.notEqual(status, 0);
  assert.match(output, /newest turns are missing/);
});

test("removing the show-more control is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/conversations.js", source =>
      source.replace("Показати більше</button>", "</button>")
            .replace("«Показати більше»", "")));
  assert.notEqual(status, 0);
  assert.match(output, /does not say it was truncated/);
});

test("an accounts console without its preview gate is caught", async () => {
  // Switching a person off is irreversible in the way that matters: they lose access
  // immediately. It gets the same gate as ingesting or rescinding.
  const {status, output} = await runWith(edit =>
    edit("public/console.html", source =>
      source.replace('<button id="account-submit" type="submit" disabled>',
                     '<button id="account-submit" type="submit">')));
  assert.notEqual(status, 0);
  assert.match(output, /account submit is enabled before anything was previewed/);
});

test("removing the accounts console surface is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/console.html", source =>
      source.replaceAll('id="console-accounts"', 'id="console-accounts-old"')));
  assert.notEqual(status, 0);
  assert.match(output, /operator console missing surface: console-accounts/);
});

test("a module imported by app but missing from the SW cache is caught", async () => {
  // The blank-offline-page failure: /conversations.js caused it once.
  const {status, output} = await runWith(edit =>
    edit("public/sw.js", source =>
      source.replace('"/conversations.js", ', "")));
  assert.notEqual(status, 0);
  assert.match(output, /service worker does not cache/);
});

test("removing the request timeout is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/api.js", source =>
      source.replace(/signal: AbortSignal\.timeout\([^)]*\),?/, "")));
  assert.notEqual(status, 0);
  assert.match(output, /no timeout or no offline signal/);
});

test("rendering a lost link as a generic error is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/app.js", source => source.replaceAll("НЕМАЄ ЗВ'ЯЗКУ", "ПОМИЛКА")));
  assert.notEqual(status, 0);
  assert.match(output, /lost link is rendered as a generic error/);
});

test("localStorage is still forbidden even though sessionStorage is now allowed", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/app.js", source =>
      `${source}\nlocalStorage.setItem("x", declaration);\n`));
  assert.notEqual(status, 0);
  assert.match(output, /persistent token storage/);
});

test("a restored declaration trusted without re-validation is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/reader_declaration.js", source =>
      source.replace(/function restoreDeclaration\(\)[\s\S]*?\n\}/,
                     'function restoreDeclaration() {\n  return JSON.parse(sessionStorage.getItem(DECLARATION_KEY));\n}')));
  assert.notEqual(status, 0);
  assert.match(output, /trusted without re-validation/);
});



test("removing the LiqPay checkout form origin from CSP is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("nginx.conf", source =>
      source.replaceAll(
        "form-action 'self' https://www.liqpay.ua;",
        "form-action 'self';",
      )));
  assert.notEqual(status, 0);
  assert.match(output, /checkout CSP/);
});


test("removing server-derived inference status is caught", async () => {
  const {status, output} = await runWith(edit =>
    edit("public/app.js", source =>
      source.replace('call("/v1/inference/status")', 'Promise.resolve({enabled:false})')));
  assert.notEqual(status, 0);
  assert.match(output, /inference assistance status/);
});
