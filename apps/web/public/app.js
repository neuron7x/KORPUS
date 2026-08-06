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

function render(answer) {
  const [verdict, tone] = VERDICT[answer.status] ?? ["ВІДМОВА", "withheld"];
  const citations = (answer.citations ?? []).map(citationCard).join("");
  const limitations = (answer.limitations ?? [])
    .map(item => `<li>${escapeHtml(item)}</li>`).join("");
  const withheld = answer.status === "answered"
    ? ""
    : `<p class="note">Порожня відповідь не означає порожній корпус. Вона означає, що
       чинного затвердженого джерела, доступного вашому допуску, для цього питання
       немає.</p>`;

  result.innerHTML = `
    <div class="verdict ${tone}">
      <span class="verdict-mark" aria-hidden="true"></span>
      <h2>${escapeHtml(verdict)}</h2>
      <span class="verdict-code">${escapeHtml(answer.decision_reason)}</span>
    </div>
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
  result.classList.remove("hidden", "error");
  result.scrollIntoView({block: "nearest", behavior: "smooth"});
}

async function ask() {
  submit.disabled = true;
  submit.textContent = "перевірка…";
  result.classList.remove("hidden", "error");
  result.innerHTML = `<p class="note">Перевіряю корпус…</p>`;
  try {
    render(await call("/v1/answers", {
      method: "POST",
      body: {text: query.value, declaration},
    }));
  } catch (error) {
    // The API answers a withheld question with a reason. Collapsing it to a status code
    // discards the only part the reader can act on.
    result.innerHTML =
      `<div class="verdict denied"><span class="verdict-mark" aria-hidden="true"></span>` +
      `<h2>${escapeHtml(error instanceof ApiRefusal ? `ВІДМОВА ${error.status}` : "ПОМИЛКА")}</h2></div>` +
      `<p class="answer-text">${escapeHtml(
        error instanceof ApiRefusal ? error.reason : "Невідома помилка")}</p>`;
    result.classList.add("error");
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

loadIdentity().catch(() => forgetIdentity("не автентифіковано"));

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => undefined);
