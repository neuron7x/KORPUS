import {call} from "./api.js";
import {
  ingestConsequence, ingestProblems, ingestionEndpoint, rescissionConsequence, rescissionProblems,
  reviewConsequence, reviewProblems,
} from "./console_rules.js";

const $ = id => document.getElementById(id);

function buildIngest(bootstrap) {
  const compartments = $("doc-compartments").value
    .split(",").map(part => part.trim().toLowerCase()).filter(Boolean);
  const document_ = {
    canonical_title: $("doc-title").value.trim(),
    corpus_id: $("doc-corpus").value.trim(),
    issuer: $("doc-issuer").value.trim(),
    jurisdiction: $("doc-jurisdiction").value.trim(),
    document_type: $("doc-type").value.trim(),
    access_tier: Number($("doc-tier").value),
    classification: $("doc-classification").value,
    compartments,
  };
  const version = {revision: $("ver-revision").value.trim(), authority: $("ver-authority").value};
  for (const [key, id] of [
    ["publication_identifier", "ver-publication-id"],
    ["source_uri", "ver-source-uri"],
    ["publication_date", "ver-publication-date"],
    ["effective_from", "ver-effective-from"],
    ["effective_until", "ver-effective-until"],
  ]) {
    const value = $(id).value.trim();
    if (value) version[key] = value;
  }
  const file = $("ingest-file").files?.[0];
  const ingestionMode = bootstrap?.capabilities?.ingestion_mode ?? null;
  const problems = ingestProblems(document_, version, Boolean(file));
  if (!ingestionEndpoint(ingestionMode)) {
    problems.push("режим внесення не підтверджено сервером; перевірте сесію ще раз");
  }
  return {
    body: {document: document_, version, filename: file?.name ?? null, ingestion_mode: ingestionMode},
    problems,
    file,
  };
}

async function sendIngest(payload, bootstrap) {
  const mode = payload.body.ingestion_mode;
  const endpoint = ingestionEndpoint(mode);
  if (!endpoint || bootstrap?.capabilities?.ingestion_mode !== mode) {
    throw new Error("режим внесення змінився; перегляньте запит ще раз");
  }
  const form = new FormData();
  form.append("document_json", JSON.stringify(payload.body.document));
  form.append("version_json", JSON.stringify(payload.body.version));
  form.append("file", payload.file);
  const result = await call(endpoint, {method: "POST", form});
  if (mode === "durable_async") {
    $("job-id").value = result.id;
    $("job-form").requestSubmit();
  }
  return result;
}

function buildReview() {
  const body = {
    target: $("review-target").value,
    note: $("review-note").value.trim(),
    acknowledge_near_duplicate: $("review-ack-duplicate").checked,
    acknowledge_extraction_quality: $("review-ack-extraction").checked,
  };
  const tier = $("review-tier").value;
  if (tier !== "") body.access_tier = Number(tier);
  const versionId = $("review-version-id").value.trim();
  return {body, problems: reviewProblems(body, versionId), versionId};
}

const sendReview = payload =>
  call(`/v1/document-versions/${encodeURIComponent(payload.versionId)}/review`,
    {method: "POST", body: payload.body});

function buildRescission() {
  const body = {note: $("rescind-note").value.trim()};
  const at = $("rescind-at").value;
  if (at) body.rescinded_at = new Date(at).toISOString();
  const versionId = $("rescind-version-id").value.trim();
  return {body, problems: rescissionProblems(body, versionId), versionId};
}

const sendRescission = payload =>
  call(`/v1/document-versions/${encodeURIComponent(payload.versionId)}/rescission`,
    {method: "POST", body: payload.body});

export function wireMutationForms(gate, getBootstrap) {
  gate($("ingest-form"), $("ingest-preview"), $("ingest-submit"), $("ingest-result"),
    () => buildIngest(getBootstrap()), ingestConsequence,
    payload => sendIngest(payload, getBootstrap()),
    (_, payload) => payload.body.ingestion_mode === "durable_async" ? "Прийнято до обробки" : "Виконано");
  gate($("review-form"), $("review-preview"), $("review-submit"), $("review-result"),
    buildReview, reviewConsequence, sendReview);
  gate($("rescind-form"), $("rescind-preview"), $("rescind-submit"), $("rescind-result"),
    buildRescission, rescissionConsequence, sendRescission);
}
