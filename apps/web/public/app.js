// The reader's surface: declare, ask, read the evidence.
//
// Two things this file refuses to blur.
//
// The identity the server verified and the identity the operator declared are rendered
// as two different chips, never merged into one line that reads like a badge. Access is
// decided by the OIDC subject and the entitlement profile; the name and specialty are
// typed on a keyboard. NIST SP 800-63-3 separates identity proofing from
// authentication, and an interface that prints them together has quietly asserted a
// proofing level nobody performed.
//
// An answer and a refusal get the same amount of screen. A refusal here is the system
// working — "no current approved source your clearance can reach holds this" — and an
// interface that renders it as an error teaches operators to retry until they get prose.

import {
  ApiRefusal, call, clearBearerToken, escapeHtml, loginUrl, setBearerToken,
} from "./api.js";

const $ = id => document.getElementById(id);

const entry = $("entry");
const standing = $("standing");
const askSection = $("ask-section");
const declarationForm = $("declaration-form");
const queryForm = $("query-form");
const query = $("query");
const submit = $("submit");
const result = $("result");
const errors = $("entry-errors");
const identityState = $("identity-state");

let identity = null;
//: In memory for the life of the tab. Not localStorage: the rule in this tree is that
//: nothing about a session outlives the tab, and a declaration that survives a shift
//: change is a declaration attributed to the wrong person.
let declaration = null;

// ---------------------------------------------------------------- identity

// On the public edge the visitor holds nothing: the edge attaches a read-only identity to
// every request, so a login button offers a flow that cannot complete and a token field
// invites pasting a credential into a page that has no use for one. Both are removed
// rather than disabled — a control that is visible and inert teaches the wrong thing
// about who is authenticated here.
const publicMode = Boolean(globalThis.window?.KORPUS_CONFIG?.publicMode);

if (publicMode) {
  for (const node of document.querySelectorAll("[data-private-only]")) node.remove();
}

function renderIdentity(loaded) {
  identity = loaded;
  if (!loaded) {
    identityState.textContent = "не автентифіковано";
    if ($("login")) $("login").hidden = false;
    if ($("logout")) $("logout").hidden = true;
    return;
  }
  identityState.innerHTML =
    `<strong>${escapeHtml(loaded.subject)}</strong>` +
    `<span class="sep">·</span>рівень ${escapeHtml(loaded.clearance)}` +
    `<span class="sep">·</span>${escapeHtml([...loaded.corpora].sort().join(", "))}`;
  if ($("login")) $("login").hidden = true;
  if ($("logout")) $("logout").hidden = false;
}

async function loadIdentity() {
  identityState.textContent = "перевірка…";
  renderIdentity(await call("/v1/auth/me"));
  return identity;
}

function forgetIdentity(message) {
  clearBearerToken();
  renderIdentity(null);
  identityState.textContent = message;
  declaration = null;
  standing.hidden = true;
  askSection.hidden = true;
  entry.hidden = false;
}

$("check-auth")?.addEventListener("click", async () => {
  setBearerToken($("bearer-token").value);
  try {
    await loadIdentity();
    $("bearer-token").value = "";
  } catch (error) {
    forgetIdentity(`відмова: ${error instanceof ApiRefusal ? error.reason : "невідома помилка"}`);
  }
});

$("login")?.addEventListener("click", () => {
  window.location.assign(loginUrl(window.location.pathname));
});

$("logout")?.addEventListener("click", async () => {
  try {
    await call("/v1/auth/logout", {method: "POST"});
    forgetIdentity("не автентифіковано");
  } catch (error) {
    identityState.textContent =
      `logout відхилено: ${error instanceof ApiRefusal ? error.reason : "невідома помилка"}`;
  }
});

// ---------------------------------------------------------------- declaration

// An error summary above the form, focusable, each item linking to its field. A message
// only beside the input is missed by a screen reader that has moved past it and by
// anyone whose viewport is below the fold. WCAG 2.2 3.3.1/3.3.3; the pattern is USWDS's.
function showErrors(problems) {
  if (!problems.length) {
    errors.hidden = true;
    errors.innerHTML = "";
    return;
  }
  errors.innerHTML =
    `<h2>Не надіслано: ${problems.length} ${problems.length === 1 ? "поле" : "поля"}</h2><ul>${
      problems.map(({field, message}) =>
        `<li><a href="#${escapeHtml(field)}">${escapeHtml(message)}</a></li>`).join("")
    }</ul>`;
  errors.hidden = false;
  errors.focus();
  for (const {field} of problems) {
    $(field)?.setAttribute("aria-invalid", "true");
  }
}

const DECLARED_FIELDS = [
  {id: "family-name", key: "family_name", label: "Прізвище", min: 1},
  {id: "given-name", key: "given_name", label: "Ім’я", min: 1},
  {id: "specialty", key: "specialty", label: "Спеціальність", min: 2},
];

function readDeclaration() {
  const problems = [];
  const declared = {};
  for (const field of DECLARED_FIELDS) {
    const element = $(field.id);
    element.removeAttribute("aria-invalid");
    const value = element.value.trim();
    if (value.length < field.min) {
      problems.push({
        field: field.id,
        message: `${field.label}: ${value ? `щонайменше ${field.min} символи` : "заповніть поле"}`,
      });
      continue;
    }
    declared[field.key] = value;
  }
  return {declared, problems};
}

function enterWorkingState() {
  $("standing-verified").textContent =
    `ДОПУСК · ${identity.subject} · рівень ${identity.clearance}`;
  $("standing-declared").textContent =
    `ЗАЯВЛЕНО · ${declaration.family_name} ${declaration.given_name} · ${declaration.specialty}`;
  entry.hidden = true;
  standing.hidden = false;
  askSection.hidden = false;
  corpus.hidden = false;
  query.focus();
}

declarationForm.addEventListener("submit", event => {
  event.preventDefault();
  const {declared, problems} = readDeclaration();
  if (!identity) {
    // In public mode there is no token field to point at — the edge holds the identity —
    // so an unauthenticated state there means the API is unreachable, not that the
    // operator forgot something. Linking the summary to a removed element would send
    // a screen reader nowhere.
    problems.unshift(
      publicMode
        ? {field: "identity-state", message: "Сервіс недоступний: особу не підтверджено"}
        : {field: "bearer-token", message: "Спершу автентифікуйтесь"},
    );
  }
  showErrors(problems);
  if (problems.length) return;
  declaration = declared;
  enterWorkingState();
});

$("standing-edit").addEventListener("click", () => {
  standing.hidden = true;
  entry.hidden = false;
  $("family-name").focus();
});

// ---------------------------------------------------------------- answer

function citationCard(citation, index) {
  const facts = [
    citation.page ? `с. ${escapeHtml(citation.page)}` : "",
    citation.section ? escapeHtml(citation.section) : "",
    `sha ${escapeHtml(String(citation.source_hash).slice(0, 12))}…`,
    `span ${escapeHtml(String(citation.span_id).slice(0, 8))}…`,
  ].filter(Boolean).map(fact => `<span>${fact}</span>`).join("");
  return `
    <article class="citation">
      <div class="citation-index">${index + 1}</div>
      <div class="citation-body">
        <h4>${escapeHtml(citation.title)} · ред. ${escapeHtml(citation.revision)}</h4>
        <blockquote>${escapeHtml(citation.quote)}</blockquote>
        <div class="meta">${facts}</div>
      </div>
    </article>`;
}

const VERDICT = {
  answered: ["ПІДСТАВА Є", "ok"],
  insufficient_evidence: ["ПІДСТАВИ НЕМАЄ", "withheld"],
  access_denied: ["ДОСТУП НЕ НАДАНО", "denied"],
  requires_human_review: ["ПОТРІБНА ЛЮДИНА", "withheld"],
};

// "The corpus holds nothing about this" and "the search did not finish" are the same
// HTTP status and the same `insufficient_evidence`, and they were rendered under the
// same three words. A reader takes the heading, not the small print: told ПІДСТАВИ
// НЕМАЄ about a rule that exists, they stop looking. These reasons get their own
// verdict, because the system did not establish an absence — it ran out of time or lost
// a dependency.
const UNFINISHED = new Set([
  "retrieval_deadline_exceeded",
  "retrieval_dependency_unavailable",
]);

function render(answer, question) {
  const [verdict, tone] = UNFINISHED.has(answer.decision_reason)
    ? ["ПОШУК НЕ ЗАВЕРШЕНО", "denied"]
    : VERDICT[answer.status] ?? ["ВІДМОВА", "withheld"];
  const citations = (answer.citations ?? []).map(citationCard).join("");
  const limitations = (answer.limitations ?? [])
    .map(item => `<li>${escapeHtml(item)}</li>`).join("");
  const withheld = answer.status === "answered"
    ? ""
    : UNFINISHED.has(answer.decision_reason)
      ? `<p class="note">Це не відповідь про корпус. Пошук не дійшов до кінця, тож про
         наявність чи відсутність підстави нічого не сказано. Спробуйте ще раз або
         звузьте питання.</p>`
      : `<p class="note">Порожня відповідь не означає порожній корпус. Вона означає, що
         чинного затвердженого джерела, доступного вашому допуску, для цього питання
         немає.</p>`;

  const block = document.createElement("article");
  block.className = "turn";
  block.innerHTML = `
    <p class="turn-question"><span class="turn-mark" aria-hidden="true"></span>${
      escapeHtml(question)}</p>
    <div class="verdict ${tone}">
      <span class="verdict-mark" aria-hidden="true"></span>
      <h2>${escapeHtml(verdict)}</h2>
      <span class="verdict-code">${escapeHtml(answer.decision_reason)}</span>
    </div>
    ${answer.opening ? `<p class="answer-opening">${escapeHtml(answer.opening)}
      <span class="answer-opening-mark">склала система з цитат нижче</span></p>` : ""}
    <p class="answer-text">${escapeHtml(answer.text).replaceAll("\n", "<br>")}</p>
    ${withheld}
    <dl class="metrics">
      <div><dt>Ranking utility</dt><dd>${Number(answer.retrieval_score).toFixed(3)}</dd></div>
      <div><dt>Покриття доказом</dt><dd>${Number(answer.evidence_coverage).toFixed(3)}</dd></div>
      <div><dt>Цитат</dt><dd>${(answer.citations ?? []).length}</dd></div>
      <div><dt>Редакція корпусу</dt><dd>${escapeHtml(answer.corpus_release)}</dd></div>
    </dl>
    <p class="note">Ranking utility не є ймовірністю правильності.</p>
    ${citations}
    ${limitations ? `<h3>Межі цієї відповіді</h3><ul class="limits">${limitations}</ul>` : ""}`;
  // Appended, not replaced. A shift is a sequence of questions — "а якщо вночі?", "а для
  // взводу?" — and an interface that erases the previous answer to show the next makes
  // the reader retype what they already asked to compare two sources.
  result.append(block);
  result.classList.remove("hidden", "error");
  block.scrollIntoView({block: "nearest", behavior: "smooth"});
}

async function ask() {
  const question = query.value.trim();
  submit.disabled = true;
  submit.textContent = "перевірка…";
  result.classList.remove("hidden", "error");
  const pending = document.createElement("p");
  pending.className = "note pending";
  pending.textContent = "Перевіряю корпус…";
  result.append(pending);
  try {
    const answer = await call("/v1/answers", {
      method: "POST",
      body: {text: question, declaration},
    });
    pending.remove();
    render(answer, question);
    // Cleared only on success: a question that failed is still in the box, so the
    // reader retries rather than retypes.
    query.value = "";
  } catch (error) {
    pending.remove();
    // The API answers a withheld question with a reason. Collapsing it to a status code
    // discards the only part the reader can act on.
    const block = document.createElement("article");
    block.className = "turn";
    block.innerHTML =
      `<p class="turn-question"><span class="turn-mark" aria-hidden="true"></span>${
        escapeHtml(question)}</p>` +
      `<div class="verdict denied"><span class="verdict-mark" aria-hidden="true"></span>` +
      `<h2>${escapeHtml(error instanceof ApiRefusal ? `ВІДМОВА ${error.status}` : "ПОМИЛКА")}</h2></div>` +
      `<p class="answer-text">${escapeHtml(
        error instanceof ApiRefusal ? error.reason : "Невідома помилка")}</p>`;
    result.append(block);
    block.scrollIntoView({block: "nearest", behavior: "smooth"});
  } finally {
    submit.disabled = false;
    submit.textContent = "Знайти доказ";
  }
}

queryForm.addEventListener("submit", event => {
  event.preventDefault();
  if (query.value.trim().length < 3) {
    showErrors([{field: "query", message: "Питання: щонайменше 3 символи"}]);
    return;
  }
  showErrors([]);
  void ask();
});

// A multi-line field swallows Enter, so without this the only way to submit is the mouse.
query.addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    queryForm.requestSubmit();
  }
});


// ---------------------------------------------------------------- corpus

// The corpus listing is a fact about scope, not an answer, and it is rendered as one:
// counts per subject and the titles under them. No relevance, no ranking, nothing that
// could be mistaken for the system having found something.
//
// Loaded once, on first open. Listing every document is a large response and requesting
// it on page load would spend it on every visitor who only wanted to ask a question.
const corpus = $("corpus");
const corpusBody = $("corpus-body");
let corpusLoaded = false;

function groupByType(documents) {
  const groups = new Map();
  for (const document_ of documents) {
    const key = document_.document_type || "без розділу";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(document_);
  }
  return [...groups.entries()].sort((left, right) => right[1].length - left[1].length);
}

function renderCorpus(documents) {
  if (!documents.length) {
    corpusBody.innerHTML = `<p class="note">Корпус порожній для вашого допуску.</p>`;
    return;
  }
  const groups = groupByType(documents);
  corpusBody.innerHTML =
    `<p class="corpus-total"><strong>${documents.length}</strong> документів · ` +
    `<strong>${groups.length}</strong> розділів · доступних вашому допуску</p>` +
    groups.map(([type, items]) =>
      `<details class="corpus-group"><summary>${escapeHtml(type)} ` +
      `<span class="corpus-count">${items.length}</span></summary><ul>${
        items.slice(0, 200).map(item =>
          `<li>${escapeHtml(item.canonical_title)}</li>`).join("")
      }${
        // Named rather than silently cut: a list that stops at two hundred and says
        // nothing reads as a complete list of two hundred.
        items.length > 200 ? `<li class="note">…і ще ${items.length - 200}</li>` : ""
      }</ul></details>`).join("");
}

corpus.addEventListener("toggle", () => {
  if (!corpus.open || corpusLoaded) return;
  corpusLoaded = true;
  call("/v1/documents")
    .then(renderCorpus)
    .catch(error => {
      corpusLoaded = false;
      corpusBody.innerHTML = `<p class="note">Перелік недоступний: ${escapeHtml(
        error instanceof ApiRefusal ? error.reason : "невідома помилка")}</p>`;
    });
});

loadIdentity().catch(() => forgetIdentity("не автентифіковано"));

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => undefined);
