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

// Every outcome panel starts with a sentence rather than an empty box. An empty panel
// beside a form reads as "nothing happened yet" and as "it ran and produced nothing",
// and those are different states.
const IDLE = {
  "ingest-result": "Тут з’явиться попередній перегляд і результат внесення.",
  "job-result": "Стан завдання показується тут.",
  "review-result": "Тут з’явиться попередній перегляд рішення та відповідь сервера.",
  "rescind-result": "Тут з’явиться попередній перегляд скасування чинності.",
  "documents-result": "Натисніть «Оновити перелік».",
  "spans-result": "Фрагменти вибраної версії показуються тут.",
  "audit-verify-result": "Натисніть «Перевірити ланцюг».",
  "audit-events-result": "Події вказаного трасування показуються тут.",
};

function idle(target) {
  target.classList.remove("error");
  target.innerHTML = `<p class="idle">${escapeHtml(IDLE[target.id] ?? "")}</p>`;
}

function busy(target, message) {
  target.classList.remove("error");
  target.innerHTML = `<p class="idle">${escapeHtml(message)}</p>`;
}

function renderRefusal(target, error) {
  if (error instanceof ApiRefusal) {
    target.innerHTML =
      `<p class="refusal">Відмова ${escapeHtml(error.status)}</p>` +
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
    `<h4>Наслідок</h4><p class="consequence">${escapeHtml(consequence)}</p>`;
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
    busy(outcome, "Надсилаю…");
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

// The identifiers are the whole point of the list: every other console asks for a
// version or document id, and copying one out of a JSON dump by hand is how the wrong
// version gets approved.
function copyable(value, shorten = true) {
  // Shown short, copied whole. A UUID rendered in full inside a table column forces a
  // horizontal scrollbar over the one piece of data the reader came for, and reading it
  // by eye is not what identifiers are for.
  const shown = shorten ? `${String(value).slice(0, 8)}…` : String(value);
  return `<button type="button" class="copyable" data-copy="${escapeHtml(value)}" ` +
    `title="${escapeHtml(value)} — натисніть, щоб скопіювати">${escapeHtml(shown)}</button>`;
}

function renderDocuments(target, documents) {
  target.classList.remove("error");
  if (!documents.length) {
    target.innerHTML =
      `<h4>Документи</h4><p class="reason">Жодного документа не доступно вашій ідентичності. ` +
      `Це не означає, що корпус порожній.</p>`;
    return;
  }
  const rows = documents.map(record => `
    <tr>
      <td>${escapeHtml(record.canonical_title)}</td>
      <td>${escapeHtml(record.issuer)}</td>
      <td>${escapeHtml(record.corpus_id)}</td>
      <td>${escapeHtml(record.classification)} · рівень ${escapeHtml(record.access_tier)}</td>
      <td>${copyable(record.id)}</td>
    </tr>`).join("");
  target.innerHTML =
    `<h4>Документи (${documents.length})</h4>` +
    `<div class="table-scroll"><table>` +
    `<caption>Доступні вашій ідентичності. Натисніть на ідентифікатор, щоб скопіювати.</caption>` +
    `<thead><tr><th>Назва</th><th>Видавець</th><th>Корпус</th><th>Класифікація</th><th>Ідентифікатор</th></tr></thead>` +
    `<tbody>${rows}</tbody></table></div>`;
}

function renderSpans(target, spans, asOf) {
  target.classList.remove("error");
  const when = asOf || "сьогодні";
  if (!spans.length) {
    // Not "no spans": a version outside its validity window on the date asked about is
    // retrievable on other dates, and reporting it as empty would read as data loss.
    target.innerHTML =
      `<h4>Фрагменти</h4><p class="reason">Жодного фрагмента не доступно вашій ідентичності ` +
      `станом на ${escapeHtml(when)}. Це може означати, що версія не чинна на цю дату, ` +
      `а не що вона порожня.</p>`;
    return;
  }
  const items = spans.map(span => `
    <article class="span-item">
      <h5>№${escapeHtml(span.ordinal)}${span.page ? ` · с.${escapeHtml(span.page)}` : ""}${
        span.section ? ` · ${escapeHtml(span.section)}` : ""}</h5>
      <p>${escapeHtml(span.text)}</p>
      ${copyable(span.span_id)}
    </article>`).join("");
  target.innerHTML = `<h4>Фрагменти (${spans.length}) станом на ${escapeHtml(when)}</h4>${items}`;
}

const JOB_STATE = {
  queued: ["wait", "У черзі: ще не бралося в роботу"],
  running: ["wait", "Виконується"],
  succeeded: ["ok", "Виконано: версія в карантині й чекає на рецензента"],
  retryable: ["wait", "Помилка, буде повторено"],
  dead_letter: ["bad", "Вичерпано спроби: потрібне рішення оператора"],
};

function renderJob(target, job) {
  target.classList.remove("error");
  const [tone, label] = JOB_STATE[job.state] ?? ["bad", "Стан невідомий"];
  // error_detail is the whole reason for looking: a dead-lettered job reporting only
  // "dead_letter" sends the curator to the database.
  const detail = job.error_detail
    ? `<p class="reason">${escapeHtml(job.error_detail)}</p>`
    : "";
  target.innerHTML =
    `<h4>Завдання ${escapeHtml(job.kind ?? "")}</h4>` +
    `<p class="status-line"><span class="dot ${tone}"></span>${escapeHtml(label)}</p>` +
    `<p class="reason">Спроб: ${escapeHtml(job.attempts)} з ${escapeHtml(job.max_attempts)}.</p>` +
    detail +
    `<pre>${escapeHtml(JSON.stringify(job, null, 2))}</pre>`;
  target.classList.toggle("error", tone === "bad");
}

function renderAuditVerification(target, verification) {
  const intact = Boolean(verification.valid);
  const anchor = verification.anchor_pending
    ? `Зовнішній якір позаду голови на ${escapeHtml(verification.anchor_pending)} подій: ` +
      `недоставлена робота, а не порушення.`
    : "Зовнішній якір узгоджений з головою ланцюга.";
  const broken = intact
    ? ""
    : `<p class="reason">Перша невідповідність: послідовність ` +
      `${escapeHtml(verification.first_invalid_sequence ?? "?")}. Причина: ` +
      `${escapeHtml(verification.reason ?? "не вказано")}.</p>`;
  target.innerHTML =
    `<h4>Ланцюг аудиту</h4>` +
    `<p class="status-line"><span class="dot ${intact ? "ok" : "bad"}"></span>` +
    `${intact ? "Ланцюг цілісний" : "Ланцюг порушено"}</p>` +
    `<p class="reason">Подій: ${escapeHtml(verification.event_count)}. ${anchor}</p>` +
    broken +
    `<pre>${escapeHtml(JSON.stringify(verification, null, 2))}</pre>`;
  target.classList.toggle("error", !intact);
}

function renderEvents(target, events) {
  target.classList.remove("error");
  if (!events.length) {
    target.innerHTML =
      `<h4>Події трасування</h4><p class="reason">Подій із таким trace id немає. ` +
      `Trace id живе в заголовку відповіді запиту, який ви розслідуєте.</p>`;
    return;
  }
  const rows = events.map(event => `
    <tr>
      <td><code>${escapeHtml(event.sequence ?? "")}</code></td>
      <td>${escapeHtml(event.occurred_at ?? "")}</td>
      <td>${escapeHtml(event.actor_subject ?? "")}</td>
      <td>${escapeHtml(event.action ?? "")}</td>
      <td>${escapeHtml(event.resource_type ?? "")}</td>
    </tr>`).join("");
  target.innerHTML =
    `<h4>Події трасування (${events.length})</h4>` +
    `<div class="table-scroll"><table>` +
    `<caption>Послідовність, мить, суб’єкт, дія, ресурс.</caption>` +
    `<thead><tr><th>#</th><th>Коли</th><th>Хто</th><th>Дія</th><th>Ресурс</th></tr></thead>` +
    `<tbody>${rows}</tbody></table></div>` +
    `<pre>${escapeHtml(JSON.stringify(events, null, 2))}</pre>`;
}

// ---------------------------------------------------------------- tabs

const TABS = ["console-curator", "console-reviewer", "console-corpus", "console-auditor"];

function selectTab(id) {
  for (const name of TABS) {
    const tab = $(`tab-${name}`);
    const panel = $(name);
    const selected = name === id;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    panel.hidden = !selected;
  }
}

function wireTabs() {
  for (const [index, name] of TABS.entries()) {
    const tab = $(`tab-${name}`);
    tab.addEventListener("click", () => selectTab(name));
    // Arrow keys are how a screen-reader user moves between tabs; without them the
    // tablist role is a promise the page does not keep.
    tab.addEventListener("keydown", event => {
      const step = {ArrowRight: 1, ArrowLeft: -1}[event.key];
      if (step === undefined) return;
      const shown = TABS.filter(candidate => !$(`tab-${candidate}`).hidden);
      if (shown.length < 2) return;
      const position = shown.indexOf(TABS[index]);
      const next = shown[(position + step + shown.length) % shown.length];
      event.preventDefault();
      selectTab(next);
      $(`tab-${next}`).focus();
    });
  }
}

// ---------------------------------------------------------------- identity

function applyIdentity(currentIdentity) {
  const visible = new Set(currentIdentity ? visibleConsoles(currentIdentity) : []);
  for (const name of TABS) {
    $(`tab-${name}`).hidden = !visible.has(name);
    $(name).hidden = true;
  }
  $("console-none").hidden = !(currentIdentity && visible.size === 0);
  const first = TABS.find(name => visible.has(name));
  if (first) selectTab(first);
}

async function loadIdentity() {
  identityState.textContent = "Перевірка…";
  const loaded = await call("/v1/auth/me");
  identityState.innerHTML =
    `<strong>${escapeHtml(loaded.subject)}</strong> · clearance ${escapeHtml(loaded.clearance)} · ` +
    `${escapeHtml([...loaded.roles].sort().join(", "))}`;
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
wireTabs();
for (const id of Object.keys(IDLE)) idle($(id));

// One listener rather than one per identifier: the tables are rewritten on every
// refresh, so per-element handlers would have to be re-attached each time.
document.addEventListener("click", async event => {
  const trigger = event.target.closest?.(".copyable");
  if (!trigger) return;
  try {
    await navigator.clipboard.writeText(trigger.dataset.copy);
    const original = trigger.textContent;
    trigger.textContent = "скопійовано";
    setTimeout(() => { trigger.textContent = original; }, 900);
  } catch {
    // Clipboard access can be refused; the identifier is still selectable by hand.
  }
});

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

$("job-form").addEventListener("submit", async event => {
  event.preventDefault();
  const target = $("job-result");
  const jobId = $("job-id").value.trim();
  if (!jobId) {
    renderProblems(target, ["ідентифікатор завдання: обов'язковий"]);
    return;
  }
  busy(target, "Читаю стан…");
  try {
    renderJob(target, await call(`/v1/ingestion-jobs/${encodeURIComponent(jobId)}`));
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
  busy(target, "Читаю фрагменти…");
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

$("documents-refresh").addEventListener("click", async () => {
  const target = $("documents-result");
  busy(target, "Читаю перелік…");
  try {
    renderDocuments(target, await call("/v1/documents"));
  } catch (error) {
    renderRefusal(target, error);
  }
});

$("audit-verify").addEventListener("click", async () => {
  const target = $("audit-verify-result");
  busy(target, "Перевіряю ланцюг…");
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
  busy(target, "Читаю події…");
  try {
    renderEvents(target, await call(
      `/v1/audit/events?trace_id=${encodeURIComponent(trace)}&limit=${limit}`));
  } catch (error) {
    renderRefusal(target, error);
  }
});

loadIdentity().catch(() => forgetIdentity("Не автентифіковано."));
