import {call} from "./api.js";
import {
  ingestConsequence, ingestProblems, rescissionConsequence, rescissionProblems,
  reviewConsequence, reviewProblems,
} from "./console_rules.js";

const $ = id => document.getElementById(id);

function buildIngest() {
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
  return {
    body: {document: document_, version, filename: file?.name ?? null},
    problems: ingestProblems(document_, version, Boolean(file)),
    file,
  };
}

async function sendIngest(payload) {
  const form = new FormData();
  form.append("document_json", JSON.stringify(payload.body.document));
  form.append("version_json", JSON.stringify(payload.body.version));
  form.append("file", payload.file);
  return call("/v1/documents/ingest", {method: "POST", form});
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

export function wireMutationForms(gate) {
  gate($("ingest-form"), $("ingest-preview"), $("ingest-submit"), $("ingest-result"),
    buildIngest, ingestConsequence, sendIngest);
  gate($("review-form"), $("review-preview"), $("review-submit"), $("review-result"),
    buildReview, reviewConsequence, sendReview);
  gate($("rescind-form"), $("rescind-preview"), $("rescind-submit"), $("rescind-result"),
    buildRescission, rescissionConsequence, sendRescission);
}
