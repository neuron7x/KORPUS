// Operator consoles: ingestion, review, rescission, corpus, audit.
//
// WEB-001 recorded that the interface covered question-and-answer and nothing else, so
// ingestion, quarantine, review, approval and audit inspection were done by hand
// against the API or the database. The acceptance predicate is that every critical
// workflow is executable without raw DB/API manipulation.
//
// Three properties make that safe rather than merely possible:
//
//   1. Nothing irreversible fires without a preview. `preview` renders the exact
//      payload and the audit consequence; `submit` stays disabled until it has been
//      shown, and any subsequent edit disables it again. A form that submits on the
//      first click is how an approval lands on the wrong version id.
//   2. Validation comes from the generated contract, not from hand-copied rules. See
//      scripts/generate_web_contract.py for why.
//   3. A refusal is rendered verbatim with its status. "Something went wrong" is what
//      sends an operator back to psql, which is the behaviour this console exists to
//      remove.
//
// Which consoles appear follows the permissions the *server* reported for the identity.
// That is presentation. Authorization is the server's, every time.
//
// Every rule above lives in console_rules.js and is tested there. This file is the
// wiring: read the form, call the rule, render the outcome.

import {
  ApiRefusal, call, clearBearerToken, escapeHtml, loginUrl, setBearerToken,
} from "./api.js";
import {CONTRACT} from "./contract.js";
import {
  ingestConsequence, ingestProblems, previewMatches, rescissionConsequence,
  rescissionProblems, reviewConsequence, reviewProblems, visibleConsoles,
} from "./console_rules.js";

const $ = id => document.getElementById(id);
const identityState = $("identity-state");

// ---------------------------------------------------------------- rendering

function renderRefusal(target, error) {
  if (error instanceof ApiRefusal) {
    target.innerHTML =
      `<p class="refusal"><strong>Відмова ${error.status}</strong></p>` +
      `<p class="reason">${escapeHtml(error.reason)}</p>`;
  } else {
    target.innerHTML = `<p class="refusal">${escapeHtml(error?.message ?? "невідома помилка")}</p>`;
  }
  target.classList.add("error");
}

function renderJson(target, heading, payload) {
  target.classList.remove("error");
  target.innerHTML =
    `<h4>${escapeHtml(heading)}</h4>` +
    `<pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>`;
}

function renderPreview(target, payload, consequence) {
  target.classList.remove("error");
  target.innerHTML =
    `<h4>Буде надіслано</h4><pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>` +
    `<h4>Наслідок в аудиті</h4><p class="reason">${escapeHtml(consequence)}</p>`;
}

function renderProblems(target, problems) {
  target.classList.add("error");
  target.innerHTML =
    `<h4>Запит не надіслано</h4><ul>${
      problems.map(problem => `<li>${escapeHtml(problem)}</li>`).join("")
    }</ul>`;
}

// ---------------------------------------------------------------- enums

function option(value, label) {
  const element = document.createElement("option");
  element.value = String(value);
  element.textContent = label ?? String(value);
  return element;
}

const TIER_LABELS = {0: "0 · public", 1: "1 · authenticated", 2: "2 · reviewed", 3: "3 · restricted"};

function fillEnums() {
  for (const value of CONTRACT.enums.Classification) $("doc-classification").append(option(value));
  for (const value of CONTRACT.enums.AccessTier) $("doc-tier").append(option(value, TIER_LABELS[value]));
  for (const value of CONTRACT.enums.AuthorityClass) $("ver-authority").append(option(value));
  // Only the states a reviewer decides. `quarantined` is where ingestion puts a version,
  // not somewhere a reviewer sends one, and offering it as a target invites an operator
  // to try a transition the server will refuse.
  for (const value of CONTRACT.enums.ReviewState) {
    if (value !== "quarantined") $("review-target").append(option(value));
  }
  $("review-tier").append(option("", "не змінювати"));
  for (const value of CONTRACT.enums.AccessTier) $("review-tier").append(option(value, TIER_LABELS[value]));
}

// ------------------------------------------------- preview / submit gating

function gate(form, previewButton, submitButton, outcome, build, consequence, send) {
  let confirmed = null;

  const invalidate = () => {
    confirmed = null;
    submitButton.disabled = true;
  };
  form.addEventListener("input", invalidate);
  form.addEventListener("change", invalidate);

  previewButton.addEventListener("click", () => {
    const payload = build();
    if (payload.problems.length) {
      renderProblems(outcome, payload.problems);
      invalidate();
      return;
    }
    confirmed = JSON.stringify(payload.body);
    submitButton.disabled = false;
    renderPreview(outcome, payload.body, consequence(payload.body));
  });

  form.addEventListener("submit", async event => {
    event.preventDefault();
    const payload = build();
    if (payload.problems.length) {
      renderProblems(outcome, payload.problems);
      invalidate();
      return;
    }
    if (!previewMatches(confirmed, payload.body)) {
      // Reachable when the form changes without firing input/change — a file chosen
      // through a drop, an autofill. The submit path re-compares rather than trusting
      // that the earlier confirmation still describes what is about to be sent.
      renderProblems(outcome, ["форма змінилася після попереднього перегляду; перегляньте ще раз"]);
      invalidate();
      return;
    }
    submitButton.disabled = true;
    try {
      renderJson(outcome, "Виконано", await send(payload));
    } catch (error) {
      renderRefusal(outcome, error);
    } finally {
      invalidate();
    }
  });
}

// ---------------------------------------------------------------- curator

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

// ---------------------------------------------------------------- reviewer

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

// ---------------------------------------------------------------- read-only

function renderDocuments(target, documents) {
  target.classList.remove("error");
  if (!documents.length) {
    target.innerHTML = "<p class=\"reason\">Жодного документа не доступно вашій ідентичності.</p>";
    return;
  }
  const rows = documents.map(record => `
    <tr>
      <td>${escapeHtml(record.canonical_title)}</td>
      <td>${escapeHtml(record.issuer)}</td>
      <td>${escapeHtml(record.corpus_id)}</td>
      <td>${escapeHtml(record.classification)}</td>
      <td>${escapeHtml(TIER_LABELS[record.access_tier] ?? record.access_tier)}</td>
      <td><code>${escapeHtml(record.id)}</code></td>
    </tr>`).join("");
  target.innerHTML = `<table><caption>Документи, доступні вашій ідентичності</caption>
    <thead><tr><th>Назва</th><th>Видавець</th><th>Корпус</th><th>Класифікація</th><th>Рівень</th><th>Ідентифікатор</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function renderSpans(target, spans, asOf) {
  target.classList.remove("error");
  if (!spans.length) {
    // Not "no spans": a version outside its validity window on the date asked about is
    // retrievable on other dates, and reporting it as empty would read as data loss.
    target.innerHTML =
      `<p class="reason">Жодного фрагмента не доступно вашій ідентичності станом на ` +
      `${escapeHtml(asOf || "сьогодні")}. Це може означати, що версія не чинна на цю ` +
      `дату, а не що вона порожня.</p>`;
    return;
  }
  const rows = spans.map(span => `
    <article class="citation">
      <h4>№${escapeHtml(span.ordinal)}${span.page ? ` · с.${escapeHtml(span.page)}` : ""}${
        span.section ? ` · ${escapeHtml(span.section)}` : ""}</h4>
      <blockquote>${escapeHtml(span.text)}</blockquote>
      <code>${escapeHtml(span.span_id)}</code>
    </article>`).join("");
  target.innerHTML = `<h4>Фрагменти (${spans.length})</h4>${rows}`;
}

function jobConsequence(job) {
  const state = {
    queued: "У черзі: ще не бралося в роботу",
    running: "Виконується",
    succeeded: "Виконано: версія в карантині й чекає на рецензента",
    retryable: "Помилка, буде повторено",
    dead_letter: "Вичерпано спроби: потрібне рішення оператора",
  }[job.state] ?? "Стан невідомий";
  return job.error_detail ? `${state} — ${job.error_detail}` : state;
}

function renderAuditVerification(target, verification) {
  const verdict = verification.valid ? "Ланцюг цілісний" : "Ланцюг порушено";
  const anchor = verification.anchor_pending
    ? "Зовнішній якір позаду голови: недоставлена робота, а не порушення."
    : "Зовнішній якір узгоджений з головою ланцюга.";
  target.innerHTML =
    `<h4>${escapeHtml(verdict)}</h4><p class="reason">${escapeHtml(anchor)}</p>` +
    `<pre>${escapeHtml(JSON.stringify(verification, null, 2))}</pre>`;
  target.classList.toggle("error", !verification.valid);
}

// ---------------------------------------------------------------- identity

function applyIdentity(currentIdentity) {
  const visible = new Set(currentIdentity ? visibleConsoles(currentIdentity) : []);
  for (const section of document.querySelectorAll(".console")) {
    section.hidden = !visible.has(section.id);
  }
  $("console-none").hidden = !(currentIdentity && visible.size === 0);
}

async function loadIdentity() {
  identityState.textContent = "Перевірка…";
  const loaded = await call("/v1/auth/me");
  identityState.textContent =
    `${loaded.subject} · clearance ${loaded.clearance} · ${[...loaded.roles].join(", ")}`;
  $("login").hidden = true;
  $("logout").hidden = false;
  applyIdentity(loaded);
  return loaded;
}

function forgetIdentity(message) {
  clearBearerToken();
  applyIdentity(null);
  $("login").hidden = false;
  $("logout").hidden = true;
  identityState.textContent = message;
}

// ---------------------------------------------------------------- wiring

fillEnums();

$("check-auth").addEventListener("click", async () => {
  setBearerToken($("bearer-token").value);
  try {
    await loadIdentity();
    $("bearer-token").value = "";
  } catch (error) {
    forgetIdentity(`Відмова: ${error instanceof ApiRefusal ? error.reason : "невідома помилка"}`);
  }
});

$("login").addEventListener("click", () => {
  window.location.assign(loginUrl(window.location.pathname));
});

$("logout").addEventListener("click", async () => {
  try {
    await call("/v1/auth/logout", {method: "POST"});
    forgetIdentity("Не автентифіковано.");
  } catch (error) {
    identityState.textContent =
      `Logout відхилено: ${error instanceof ApiRefusal ? error.reason : "невідома помилка"}`;
  }
});

gate($("ingest-form"), $("ingest-preview"), $("ingest-submit"), $("ingest-result"),
  buildIngest, ingestConsequence, sendIngest);
gate($("review-form"), $("review-preview"), $("review-submit"), $("review-result"),
  buildReview, reviewConsequence, sendReview);
gate($("rescind-form"), $("rescind-preview"), $("rescind-submit"), $("rescind-result"),
  buildRescission, rescissionConsequence, sendRescission);

$("documents-refresh").addEventListener("click", async () => {
  const target = $("documents-result");
  try {
    renderDocuments(target, await call("/v1/documents"));
  } catch (error) {
    renderRefusal(target, error);
  }
});

$("job-form").addEventListener("submit", async event => {
  event.preventDefault();
  const target = $("job-result");
  const jobId = $("job-id").value.trim();
  if (!jobId) {
    renderProblems(target, ["ідентифікатор завдання: обов'язковий"]);
    return;
  }
  try {
    const job = await call(`/v1/ingestion-jobs/${encodeURIComponent(jobId)}`);
    // The failure reason is the whole point of looking: a dead-lettered job that
    // reports only "dead_letter" sends the curator to the database for error_detail.
    renderJson(target, jobConsequence(job), job);
  } catch (error) {
    renderRefusal(target, error);
  }
});

$("spans-form").addEventListener("submit", async event => {
  event.preventDefault();
  const target = $("spans-result");
  const versionId = $("spans-version-id").value.trim();
  if (!versionId) {
    renderProblems(target, ["ідентифікатор версії: обов'язковий"]);
    return;
  }
  const asOf = $("spans-as-of").value;
  const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
  try {
    renderSpans(
      target,
      await call(`/v1/document-versions/${encodeURIComponent(versionId)}/spans${query}`),
      asOf,
    );
  } catch (error) {
    renderRefusal(target, error);
  }
});

$("audit-verify").addEventListener("click", async () => {
  const target = $("audit-verify-result");
  try {
    renderAuditVerification(target, await call("/v1/audit/verify"));
  } catch (error) {
    renderRefusal(target, error);
  }
});

$("audit-events-form").addEventListener("submit", async event => {
  event.preventDefault();
  const target = $("audit-events-result");
  const trace = $("audit-trace").value.trim();
  if (!trace) {
    renderProblems(target, ["trace id: обов'язковий"]);
    return;
  }
  const limit = Number($("audit-limit").value) || 200;
  try {
    const events = await call(
      `/v1/audit/events?trace_id=${encodeURIComponent(trace)}&limit=${limit}`);
    renderJson(target, `Події трасування (${events.length})`, events);
  } catch (error) {
    renderRefusal(target, error);
  }
});

loadIdentity().catch(() => forgetIdentity("Не автентифіковано."));
