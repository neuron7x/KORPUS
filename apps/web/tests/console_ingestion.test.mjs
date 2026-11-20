import test from "node:test";
import assert from "node:assert/strict";

import {ApiRefusal, clearBearerToken, setBearerToken} from "../public/api.js";
import {wireMutationForms} from "../public/console_mutations.js";
import {previewMatches} from "../public/console_rules.js";

function consoleFixture(t, mode) {
  const values = {
    "doc-title": "Synthetic archive catalog", "doc-corpus": "pilot-smoke",
    "doc-issuer": "KORPUS test fixture", "doc-jurisdiction": "UA",
    "doc-type": "reference", "doc-tier": "0", "doc-classification": "public",
    "ver-revision": "1", "ver-authority": "analytical",
  };
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      id, value: values[id] ?? "", files: [], submitted: 0,
      requestSubmit() { this.submitted += 1; },
    });
    return elements.get(id);
  };
  element("ingest-file").files = [new File(["A neutral archive fixture."], "archive.txt", {type: "text/plain"})];
  t.mock.method(globalThis, "fetch", async () => { throw new Error("unexpected network call"); });
  const originalDocument = globalThis.document;
  globalThis.document = {getElementById: element, cookie: ""};
  t.after(() => { globalThis.document = originalDocument; clearBearerToken(); });
  let bootstrap = {capabilities: {ingestion_mode: mode}};
  let ingestion;
  wireMutationForms((form, _preview, _submit, _result, build, consequence, send, heading) => {
    if (form.id === "ingest-form") ingestion = {build, consequence, send, heading};
  }, () => bootstrap);
  return {ingestion, element, setBootstrap: value => { bootstrap = value; }};
}

for (const [mode, endpoint, response] of [
  ["synchronous", "/v1/documents/ingest", {document: {id: "document"}, version: {id: "version", review_state: "quarantined"}}],
  ["durable_async", "/v1/ingestion-jobs/documents", {id: "accepted-job", state: "queued", result: null}],
]) {
  test(`${mode} console submits the selected route with the unchanged authenticated multipart body`, async t => {
    const {ingestion, element} = consoleFixture(t, mode);
    const requests = [];
    setBearerToken("synthetic-test-credential");
    globalThis.fetch.mock.mockImplementation(async (url, options) => {
      requests.push({url, options});
      return new Response(JSON.stringify(response), {status: mode === "synchronous" ? 201 : 202});
    });
    const payload = ingestion.build();
    assert.deepEqual(payload.problems, []);
    assert.equal(payload.body.ingestion_mode, mode);
    assert.match(ingestion.consequence(payload.body), /лише після затвердження/);
    const result = await ingestion.send(payload);
    assert.deepEqual(result, response);
    assert.equal(requests.length, 1);
    const {url, options} = requests[0];
    assert.equal(url, `/api${endpoint}`);
    assert.equal(options.method, "POST");
    assert.equal(options.headers.Authorization, "Bearer synthetic-test-credential");
    assert.equal(options.credentials, "same-origin");
    assert.deepEqual(JSON.parse(options.body.get("document_json")), payload.body.document);
    assert.deepEqual(JSON.parse(options.body.get("version_json")), payload.body.version);
    assert.equal(await options.body.get("file").text(), "A neutral archive fixture.");
    assert.equal(options.body.has("ingestion_mode"), false);
    if (mode === "durable_async") {
      assert.equal(element("job-id").value, response.id);
      assert.equal(element("job-form").submitted, 1);
      assert.equal(ingestion.heading(result, payload), "Прийнято до обробки");
      assert.match(ingestion.consequence(payload.body), /буде поставлено в чергу/);
    } else {
      assert.equal(element("job-form").submitted, 0);
      assert.equal(ingestion.heading(result, payload), "Виконано");
    }
  });
}

for (const bootstrap of [null, {}, {capabilities: {}}, {capabilities: {ingestion_mode: "unknown"}}]) {
  test(`unconfirmed ingestion mode blocks preview and submission: ${JSON.stringify(bootstrap)}`, async t => {
    const {ingestion, setBootstrap} = consoleFixture(t, "synchronous");
    setBootstrap(bootstrap);
    const payload = ingestion.build();
    assert.ok(payload.problems.some(problem => problem.includes("не підтверджено сервером")));
    await assert.rejects(ingestion.send(payload), /режим внесення змінився/);
    assert.equal(globalThis.fetch.mock.callCount(), 0);
  });
}

test("a mode change invalidates the preview and cannot silently send to another endpoint", async t => {
  const {ingestion, setBootstrap} = consoleFixture(t, "synchronous");
  const previewed = ingestion.build();
  setBootstrap({capabilities: {ingestion_mode: "durable_async"}});
  assert.equal(previewMatches(JSON.stringify(previewed.body), ingestion.build().body), false);
  await assert.rejects(ingestion.send(previewed), /перегляньте запит ще раз/);
  assert.equal(globalThis.fetch.mock.callCount(), 0);
});

test("losing the authenticated bootstrap prevents a previously previewed upload", async t => {
  const {ingestion, setBootstrap} = consoleFixture(t, "durable_async");
  const previewed = ingestion.build();
  setBootstrap(null);
  await assert.rejects(ingestion.send(previewed), /режим внесення змінився/);
  assert.equal(globalThis.fetch.mock.callCount(), 0);
});

test("a server mode conflict is surfaced without retrying the other write endpoint", async t => {
  const {ingestion, element} = consoleFixture(t, "durable_async");
  globalThis.fetch.mock.mockImplementation(async () => new Response(
    JSON.stringify({detail: "durable ingestion is disabled"}), {status: 409},
  ));
  await assert.rejects(ingestion.send(ingestion.build()), error => {
    assert.ok(error instanceof ApiRefusal);
    assert.equal(error.status, 409);
    return true;
  });
  assert.equal(globalThis.fetch.mock.callCount(), 1);
  assert.equal(element("job-form").submitted, 0);
});
