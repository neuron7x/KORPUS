// KORPUS consumer surface: identity → commercial entitlement → evidence chat.
//
// The interface is intentionally thinner than the trust kernel. Identity comes from the
// server, price comes from the server, evidence comes from the server. The browser may
// present those decisions and initiate checkout; it never manufactures one.

import {
  ApiRefusal, NetworkError, call, clearBearerToken, escapeHtml, loginUrl, setBearerToken,
} from "./api.js";
import {createBillingController} from "./billing.js";
import {askIn} from "./conversations.js";
import {
  forgetDeclaration, readDeclaration, rememberDeclaration, restoreDeclaration,
} from "./reader_declaration.js";
import {wireCorpus} from "./reader_corpus.js";
import {createConversationController} from "./reader_conversations.js";
import {UNFINISHED, VERDICT} from "./reader_verdicts.js";

const $ = id => document.getElementById(id);

const entry = $("entry");
const product = $("product");
const standing = $("standing");
const askSection = $("ask-section");
const declarationForm = $("declaration-form");
const sessionContext = $("session-context");
const queryForm = $("query-form");
const query = $("query");
const submit = $("submit");
const result = $("result");
const errors = $("entry-errors");
const identityState = $("identity-state");
const pricing = $("pricing");
const emptyChat = $("empty-chat");

let identity = null;
// Optional operator-provided context. It is kept for the tab and sent as `declaration`,
// because the audit contract already distinguishes it from authenticated identity. It
// is never required to enter the consumer chat and never grants access.
let declaration = null;
let commerce = null;

const publicMode = Boolean(globalThis.window?.KORPUS_CONFIG?.publicMode);
const conversationController = createConversationController({publicMode, result, query});

if (publicMode) {
  for (const node of document.querySelectorAll("[data-private-only]")) node.remove();
}

// ---------------------------------------------------------------- identity + product state

function renderIdentity(loaded) {
  identity = loaded;
  if (!loaded) {
    if (identityState) identityState.textContent = "не автентифіковано";
    if ($("login")) $("login").hidden = false;
    if ($("logout")) $("logout").hidden = true;
    entry.hidden = false;
    product.hidden = true;
    pricing.hidden = true;
    return;
  }
  if (identityState) {
    identityState.innerHTML =
      `<strong>${escapeHtml(loaded.subject)}</strong>` +
      `<span class="sep">·</span>${escapeHtml(loaded.clearance)}`;
  }
  if ($("login")) $("login").hidden = true;
  if ($("logout")) $("logout").hidden = false;
}

async function loadIdentity() {
  if (identityState) identityState.textContent = "перевірка…";
  renderIdentity(await call("/v1/auth/me"));
  return identity;
}

function updateStanding() {
  if (!identity) return;
  $("standing-verified").textContent = `ДОПУСК · ${identity.clearance}`;
  $("standing-declared").textContent = declaration
    ? `ЗАЯВЛЕНО · ${declaration.family_name} ${declaration.given_name} · ${declaration.specialty}`
    : "КОНТЕКСТ НЕ ЗАДАНО";
}

function enterWorkingState() {
  if (!identity) return;
  entry.hidden = true;
  product.hidden = false;
  standing.hidden = false;
  updateStanding();
  $("corpus").hidden = false;
  query.focus({preventScroll: true});
  void conversationController.start();
}

function forgetIdentity(message) {
  clearBearerToken();
  identity = null;
  commerce = null;
  forgetDeclaration();
  declaration = null;
  renderIdentity(null);
  if (identityState) identityState.textContent = message;
  result.innerHTML = "";
  result.classList.add("hidden");
}

$("check-auth")?.addEventListener("click", async () => {
  setBearerToken($("bearer-token").value);
  try {
    await loadIdentity();
    $("bearer-token").value = "";
    declaration = restoreDeclaration();
    enterWorkingState();
    if (!publicMode) await billing.refresh();
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
    if (identityState) {
      identityState.textContent =
        `logout відхилено: ${error instanceof ApiRefusal ? error.reason : "невідома помилка"}`;
    }
  }
});

// ---------------------------------------------------------------- billing

const billing = createBillingController({
  pricing,
  plansNode: $("plans"),
  statusNode: $("subscription-pill"),
  accountNode: $("account-label"),
  onState: state => {
    commerce = state;
    const locked = state.enforced && !state.active;
    askSection.hidden = locked;
    emptyChat.hidden = locked;
    if (locked) {
      pricing.hidden = false;
      $("pricing-heading").textContent = state.unavailable
        ? "Платний доступ поки не налаштований"
        : "Активуйте доступ до KORPUS";
    }
  },
});

// ---------------------------------------------------------------- optional declared session context

function showErrors(problems) {
  if (!problems.length) {
    errors.hidden = true;
    errors.innerHTML = "";
    return;
  }
  errors.innerHTML =
    `<h2>Не надіслано: ${problems.length}</h2><ul>${problems.map(({field, message}) =>
      `<li><a href="#${escapeHtml(field)}">${escapeHtml(message)}</a></li>`).join("")}</ul>`;
  errors.hidden = false;
  errors.focus();
  for (const {field} of problems) $(field)?.setAttribute("aria-invalid", "true");
}

declarationForm?.addEventListener("submit", event => {
  event.preventDefault();
  const {declared, problems} = readDeclaration();
  showErrors(problems);
  if (problems.length) return;
  declaration = rememberDeclaration(declared);
  updateStanding();
  sessionContext.open = false;
  query.focus();
});

$("standing-edit")?.addEventListener("click", () => {
  if (!sessionContext) return;
  sessionContext.open = true;
  $("family-name")?.focus();
});

// ---------------------------------------------------------------- answer presentation

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
        <h3>${escapeHtml(citation.title)} · ред. ${escapeHtml(citation.revision)}</h3>
        <blockquote>${escapeHtml(citation.quote)}</blockquote>
        <div class="meta">${facts}</div>
      </div>
    </article>`;
}

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
      ? `<p class="note">Пошук не завершив усі gates. Це не твердження про відсутність підстави.</p>`
      : `<p class="note">Відмова означає лише те, що достатнього чинного доказу для цієї відповіді не допущено.</p>`;

  const block = document.createElement("article");
  block.className = "turn";
  block.innerHTML = `
    <p class="turn-question"><span class="turn-mark" aria-hidden="true"></span>${escapeHtml(question)}</p>
    <div class="verdict ${tone}">
      <span class="verdict-mark" aria-hidden="true"></span>
      <h2>${escapeHtml(verdict)}</h2>
      <span class="verdict-code">${escapeHtml(answer.decision_reason)}</span>
    </div>
    ${answer.opening ? `<p class="answer-opening">${escapeHtml(answer.opening)}
      <span class="answer-opening-mark">система склала цей рядок лише з допущених цитат</span></p>` : ""}
    <p class="answer-text">${escapeHtml(answer.text).replaceAll("\n", "<br>")}</p>
    ${withheld}
    <dl class="metrics">
      <div><dt>Ranking utility</dt><dd>${Number(answer.retrieval_score).toFixed(3)}</dd></div>
      <div><dt>Evidence coverage</dt><dd>${Number(answer.evidence_coverage).toFixed(3)}</dd></div>
      <div><dt>Цитат</dt><dd>${(answer.citations ?? []).length}</dd></div>
      <div><dt>Corpus release</dt><dd>${escapeHtml(answer.corpus_release)}</dd></div>
    </dl>
    <p class="note">Ranking utility не є ймовірністю правильності.</p>
    ${citations}
    ${limitations ? `<h3 class="limits-heading">Межі відповіді</h3><ul class="limits">${limitations}</ul>` : ""}`;
  result.append(block);
  result.classList.remove("hidden", "error");
  emptyChat.hidden = true;
  block.scrollIntoView({block: "nearest", behavior: "smooth"});
}

async function ask() {
  const question = query.value.trim();
  submit.disabled = true;
  submit.textContent = "…";
  result.classList.remove("hidden", "error");
  emptyChat.hidden = true;
  const pending = document.createElement("p");
  pending.className = "note pending";
  pending.textContent = "Перевіряю джерела та допустимість тверджень…";
  result.append(pending);
  try {
    // Exact body shape is contract evidence: declared context accompanies the query but
    // remains a separate field and therefore can never masquerade as authenticated identity.
    const body = {text: question, declaration};
    const conversation = await conversationController.forQuestion(question);
    const answer = conversation
      ? await askIn(conversation, body)
      : await call("/v1/answers", {method: "POST", body});
    pending.remove();
    render(answer, question);
    void conversationController.refresh();
    query.value = "";
  } catch (error) {
    pending.remove();
    if (error instanceof NetworkError) {
      const block = document.createElement("article");
      block.className = "turn";
      block.innerHTML =
        `<p class="turn-question"><span class="turn-mark" aria-hidden="true"></span>${escapeHtml(question)}</p>` +
        `<div class="verdict denied"><span class="verdict-mark" aria-hidden="true"></span>` +
        `<h2>${escapeHtml(error.offline ? "НЕМАЄ ЗВ'ЯЗКУ" : "ЗВ'ЯЗОК ПЕРЕРВАВСЯ")}</h2></div>` +
        `<p class="answer-text">Питання не надіслано. Воно залишилось у полі для повторної спроби.</p>`;
      result.append(block);
      block.scrollIntoView({block: "nearest", behavior: "smooth"});
      return;
    }
    const refusal = error instanceof ApiRefusal ? error : null;
    const paywalled = refusal?.status === 402;
    const heading = paywalled ? "ПОТРІБНА ПІДПИСКА" : refusal ? `ВІДМОВА ${refusal.status}` : "ПОМИЛКА";
    const detail = refusal?.payload?.detail;
    const reason = typeof detail === "object" && detail !== null
      ? String(detail.detail ?? detail.reason ?? refusal.reason)
      : refusal?.reason ?? "Невідома помилка";
    const block = document.createElement("article");
    block.className = "turn";
    block.innerHTML =
      `<p class="turn-question"><span class="turn-mark" aria-hidden="true"></span>${escapeHtml(question)}</p>` +
      `<div class="verdict ${paywalled ? "withheld" : "denied"}"><span class="verdict-mark" aria-hidden="true"></span>` +
      `<h2>${escapeHtml(heading)}</h2></div><p class="answer-text">${escapeHtml(reason)}</p>` +
      (paywalled ? `<p class="note">Це комерційна відмова, а не висновок про базу знань.</p>` : "");
    result.append(block);
    if (paywalled && !publicMode) {
      await billing.refresh();
      pricing.scrollIntoView({block: "start", behavior: "smooth"});
    }
    block.scrollIntoView({block: "nearest", behavior: "smooth"});
  } finally {
    submit.disabled = false;
    submit.textContent = "↑";
  }
}

queryForm.addEventListener("submit", event => {
  event.preventDefault();
  if (commerce?.enforced && !commerce?.active) {
    pricing.scrollIntoView({block: "start", behavior: "smooth"});
    return;
  }
  if (query.value.trim().length < 3) {
    showErrors([{field: "query", message: "Питання має містити щонайменше 3 символи"}]);
    return;
  }
  showErrors([]);
  void ask();
});

query.addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    queryForm.requestSubmit();
  }
});

// ---------------------------------------------------------------- corpus + boot

wireCorpus({corpus: $("corpus"), body: $("corpus-body")});

loadIdentity()
  .then(async () => {
    if (!identity) return;
    declaration = restoreDeclaration();
    enterWorkingState();
    if (!publicMode) await billing.refresh();
    const returned = new URLSearchParams(window.location.search).get("billing") === "return";
    if (returned) {
      $("subscription-pill").textContent = commerce?.active
        ? "Підписка активна"
        : "Платіж прийнято провайдером · очікую callback";
    }
  })
  .catch(() => forgetIdentity("не автентифіковано"));

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => undefined);
