import {
  ApiRefusal, NetworkError, call, clearBearerToken, escapeHtml, loginUrl, setBearerToken,
} from "./api.js";
import {CHAT_STATE, createChatMachine, replayServerOutcome} from "./chat_fsm.js";
import {askIn} from "./conversations.js";
import {
  forgetDeclaration, readDeclaration, rememberDeclaration, restoreDeclaration,
} from "./reader_declaration.js";
import {wireCorpus} from "./reader_corpus.js";
import {createConversationController} from "./reader_conversations.js";
import {UNFINISHED, VERDICT} from "./reader_verdicts.js";

const $ = id => document.getElementById(id);

const themeToggle = $("theme-toggle");
let unmountCombatScene = null;

function applyTheme(combat) {
  if (combat && !document.getElementById("combat-theme")) {
    const link = document.createElement("link");
    Object.assign(link, {id: "combat-theme", rel: "stylesheet", href: "/combat.css"});
    document.head.append(link);
  }
  document.documentElement.dataset.theme = combat ? "combat" : "core";
  if (combat) {
    import("./combat_scene.js").then(({mountCombatScene}) => {
      if (document.documentElement.dataset.theme === "combat" && !unmountCombatScene) {
        unmountCombatScene = mountCombatScene();
      }
    });
  } else if (unmountCombatScene) {
    unmountCombatScene();
    unmountCombatScene = null;
  }
  themeToggle?.setAttribute("aria-pressed", String(combat));
  themeToggle?.setAttribute("aria-label", combat ? "Увімкнути основну тему" : "Увімкнути бойову тему");
  const label = themeToggle?.querySelector("[data-theme-label]");
  if (label) label.textContent = combat ? "ОСНОВНА" : "БОЙОВА";
}

let combat = false;
try {
  combat = sessionStorage.getItem("korpus-theme") === "combat";
} catch { /* Core remains canonical when browser storage is unavailable. */ }
applyTheme(combat);
themeToggle?.addEventListener("click", () => {
  combat = !combat;
  applyTheme(combat);
  try { sessionStorage.setItem("korpus-theme", combat ? "combat" : "core"); } catch { /* Applies in-memory. */ }
});

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
let bootstrap = null;
let declaration = null;
let commerce = null;
let chatMachine = createChatMachine();
const observedSources = new Map();
let traceControllerPromise;
function renderTraceState(state) {
  traceControllerPromise ??= import("./trace.js").then(({createTraceController}) => createTraceController());
  traceControllerPromise.then(controller => controller.render(state));
}

function setChatMachine(machine) {
  chatMachine = machine;
  if (product) product.dataset.chatState = machine.state;
  renderTraceState(machine.state);
}
function chatEvent(event) {
  const state = chatMachine.send(event);
  if (product) product.dataset.chatState = state;
  renderTraceState(state);
  return state;
}

const publicMode = Boolean(globalThis.window?.KORPUS_CONFIG?.publicMode);
const conversationController = createConversationController({publicMode, result, query});

if (publicMode) {
  for (const node of document.querySelectorAll("[data-private-only]")) node.remove();
}

// ---------------------------------------------------------------- identity + product state

function renderIdentity(loaded) {
  identity = loaded;
  setChatMachine(createChatMachine(loaded ? CHAT_STATE.READY : CHAT_STATE.UNAUTHENTICATED));
  if (!loaded) {
    if (identityState) identityState.textContent = "не автентифіковано";
    if ($("login")) $("login").hidden = false;
    if ($("logout")) $("logout").hidden = true;
    entry.hidden = false;
    product.hidden = true;
    pricing.hidden = true;
    $("mobile-nav").hidden = true;
    return;
  }
  if (identityState) {
    identityState.innerHTML =
      `<strong>${escapeHtml(loaded.subject)}</strong>` +
      `<span class="sep">·</span>${escapeHtml(loaded.clearance)}`;
  }
  if ($("login")) $("login").hidden = true;
  if ($("logout")) $("logout").hidden = false;
  $("mobile-nav").hidden = false;
}

async function loadIdentity() {
  if (identityState) identityState.textContent = "перевірка…";
  bootstrap = await call("/v1/client/bootstrap");
  renderIdentity(bootstrap.identity);
  return identity;
}

function hasPermission(permission) {
  return new Set(bootstrap?.effective_permissions ?? []).has(permission);
}

function updateStanding() {
  if (!identity) return;
  $("standing-verified").textContent = `ДОПУСК · ${identity.clearance}`;
  $("standing-declared").textContent = declaration
    ? `ЗАЯВЛЕНО · ${declaration.family_name} ${declaration.given_name} · ${declaration.specialty}`
    : "КОНТЕКСТ НЕ ЗАДАНО";
}

async function loadInferenceStatus() {
  const node = $("inference-state");
  if (!node) return;
  try {
    const state = await call("/v1/inference/status");
    if (!state.enabled) {
      node.textContent = "МОДЕЛЬ · ВИМКНЕНО";
      node.dataset.tone = "off";
      node.title = "Відповідь працює лише через детермінований evidence path.";
      return;
    }
    node.textContent = `МОДЕЛЬ · ${String(state.provider).toUpperCase()}`;
    node.dataset.tone = "on";
    node.title = `${state.model}. Модель допомагає пошуку/композиції; authority = ${state.answer_authority}.`;
  } catch {
    node.textContent = "МОДЕЛЬ · СТАН НЕВІДОМИЙ";
    node.dataset.tone = "unknown";
  }
}

function enterWorkingState() {
  if (!identity) return;
  entry.hidden = true;
  product.hidden = false;
  standing.hidden = false;
  updateStanding();
  $("corpus").hidden = !hasPermission("document:list");
  if (hasPermission("answer:read")) void conversationController.start();
}

function forgetIdentity(message) {
  clearBearerToken();
  identity = null;
  bootstrap = null;
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
    const route = await renderWorkspaceRoute();
    if (route?.id === "chat" || route?.id === "chat-conversation") query.focus({preventScroll:true});
    await loadInferenceStatus();
    if (!publicMode) await refreshBilling();
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

let billingPromise = null;
function getBilling() {
  if (publicMode) return Promise.resolve(null);
  if (!billingPromise) {
    billingPromise = import("./billing.js").then(({createBillingController}) =>
      createBillingController({
        pricing,
        plansNode: $("plans"),
        statusNode: $("subscription-pill"),
        accountNode: $("account-label"),
        onState: state => {
          commerce = state;
          const locked = state.enforced && !state.active;
          document.body.dataset.access = locked ? "locked" : "active";
          askSection.hidden = locked;
          emptyChat.hidden = locked;
          if (locked) {
            pricing.hidden = false;
            $("pricing-heading").textContent = state.unavailable
              ? "Платний доступ поки не налаштований"
              : "Відкрийте доступ до KORPUS";
            requestAnimationFrame(() => {
              pricing.scrollIntoView({block: "start", behavior: "smooth"});
              pricing.focus({preventScroll: true});
            });
          }
        },
      })
    );
  }
  return billingPromise;
}

async function refreshBilling() {
  const controller = await getBilling();
  if (controller) await controller.refresh();
}

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
        <button type="button" class="secondary citation-open" data-open-span="${escapeHtml(String(citation.span_id))}" data-version-id="${escapeHtml(String(citation.version_id))}">Відкрити точний фрагмент</button>
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
  for (const citation of answer.citations ?? []) {
    observedSources.set(String(citation.span_id), Object.freeze({...citation}));
  }
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
    <details class="answer-meta"><summary>Деталі перевірки</summary>
      <dl class="metrics">
        <div><dt>Ranking utility</dt><dd>${Number(answer.retrieval_score).toFixed(3)}</dd></div>
        <div><dt>Evidence coverage</dt><dd>${Number(answer.evidence_coverage).toFixed(3)}</dd></div>
        <div><dt>Цитат</dt><dd>${(answer.citations ?? []).length}</dd></div>
        <div><dt>Corpus release</dt><dd>${escapeHtml(answer.corpus_release)}</dd></div>
      </dl><p class="note">Ranking utility не є ймовірністю правильності.</p>
    </details>
    ${citations}
    ${limitations ? `<h3 class="limits-heading">Межі відповіді</h3><ul class="limits">${limitations}</ul>` : ""}`;
  result.append(block);
  import("./decision_field.js").then(({createDecisionField}) => {
    const anchor = block.querySelector(".answer-meta");
    anchor?.insertAdjacentElement("afterend", createDecisionField(answer));
  });
  result.classList.remove("hidden", "error");
  emptyChat.hidden = true;
  block.scrollIntoView({block: "nearest", behavior: "smooth"});
}

async function ask() {
  const question = query.value.trim();
  if (chatMachine.state !== CHAT_STATE.READY) setChatMachine(createChatMachine(CHAT_STATE.READY));
  chatEvent("SUBMIT");
  chatEvent("REQUEST_SENT");
  submit.disabled = true;
  submit.setAttribute("aria-busy", "true");
  query.setAttribute("aria-busy", "true");
  result.setAttribute("aria-busy", "true");
  submit.textContent = "…";
  result.classList.remove("hidden", "error");
  emptyChat.hidden = true;
  const pending = document.createElement("p");
  pending.className = "note pending";
  pending.textContent = "Шукаю джерела → перевіряю доказ → за потреби компоную без нових фактів…";
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
    replayServerOutcome(chatMachine, answer);
    if (product) product.dataset.chatState = chatMachine.state;
    renderTraceState(chatMachine.state);
    render(answer, question);
    void conversationController.refresh();
    query.value = "";
  } catch (error) {
    pending.remove();
    if (error instanceof ApiRefusal && error.status === 403 && chatMachine.state === CHAT_STATE.POLICY_CHECK) {
      chatEvent("SERVER_DENIED");
    } else if ([CHAT_STATE.QUERY_SUBMITTED, CHAT_STATE.POLICY_CHECK, CHAT_STATE.RETRIEVING].includes(chatMachine.state)) {
      chatEvent("FAIL");
    }
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
      await refreshBilling();
      pricing.scrollIntoView({block: "start", behavior: "smooth"});
    }
    block.scrollIntoView({block: "nearest", behavior: "smooth"});
  } finally {
    submit.disabled = false;
    submit.removeAttribute("aria-busy");
    query.removeAttribute("aria-busy");
    result.removeAttribute("aria-busy");
    submit.textContent = "↑";
    resizeComposer();
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

function resizeComposer() {
  query.style.height = "auto";
  query.style.height = `${Math.min(query.scrollHeight, 190)}px`;
}

for (const action of document.querySelectorAll(".quick-action[data-template]")) {
  action.addEventListener("click", () => {
    query.value = action.dataset.template ?? "";
    resizeComposer();
    query.focus();
  });
}

query.addEventListener("input", resizeComposer);
query.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    queryForm.requestSubmit();
  }
});
resizeComposer();

// ---------------------------------------------------------------- exact evidence + routed workspace

const evidenceDialog = $("evidence-dialog");
const evidenceText = $("evidence-text");
const evidenceMeta = $("evidence-meta");
const evidenceValidity = $("evidence-validity");
let evidenceReturnFocus = null;

function evidenceField(label, value) {
  const dt = document.createElement("dt"); dt.textContent = label;
  const dd = document.createElement("dd"); dd.textContent = value == null || value === "" ? "—" : String(value);
  evidenceMeta.append(dt, dd);
}

async function openEvidence(spanId, expectedVersion, opener) {
  evidenceReturnFocus = opener ?? document.activeElement;
  evidenceText.textContent = "Завантаження точного фрагмента…";
  evidenceMeta.replaceChildren();
  evidenceValidity.textContent = "Повторна серверна авторизація джерела…";
  if (!evidenceDialog.open) evidenceDialog.showModal();
  try {
    const span = await call(`/v1/spans/${encodeURIComponent(spanId)}`);
    if (String(span.id) !== String(spanId) || (expectedVersion && String(span.version_id) !== String(expectedVersion))) {
      throw new Error("source identity mismatch");
    }
    evidenceText.textContent = span.text;
    const until = span.rescinded_at ? `відкликано ${span.rescinded_at}` : span.effective_until ? `до ${span.effective_until}` : "кінцеву дату не задано";
    evidenceValidity.textContent = `ред. ${span.revision} · чинність від ${span.effective_from ?? span.publication_date ?? "невідомо"} · ${until}`;
    evidenceField("Документ", span.document_title);
    evidenceField("Version ID", span.version_id);
    evidenceField("Span ID", span.id);
    evidenceField("Locator", [span.page ? `с. ${span.page}` : "", span.section ?? "", `ordinal ${span.ordinal}`].filter(Boolean).join(" · "));
    evidenceField("Authority", span.authority);
    evidenceField("Source SHA-256", span.source_hash);
    evidenceField("Span SHA-256", span.text_hash);
    evidenceField("Source URI", span.source_uri);
    evidenceText.focus({preventScroll:true});
  } catch (error) {
    evidenceValidity.textContent = "Джерело не розкрито. 404 не відрізняє відсутність від відсутності права.";
    evidenceText.textContent = error instanceof ApiRefusal ? error.reason : "Не вдалося повторно авторизувати точний фрагмент.";
  }
}

document.addEventListener("click", event => {
  const open = event.target.closest?.("[data-open-span]");
  if (open) void openEvidence(open.dataset.openSpan, open.dataset.versionId, open);
});
$("evidence-close")?.addEventListener("click", () => evidenceDialog?.close());
evidenceDialog?.addEventListener("close", () => evidenceReturnFocus?.focus?.({preventScroll:true}));

let workspaceRouterPromise = null;
function getWorkspaceRouter() {
  if (!workspaceRouterPromise) {
    workspaceRouterPromise = import("./workspace_routes.js").then(({createWorkspaceRouter}) =>
      createWorkspaceRouter({
        view: $("route-view"),
        nav: document,
        chatNodes: [...document.querySelectorAll("[data-chat-only]")],
        isAuthenticated: () => Boolean(identity),
        getBootstrap: () => bootstrap,
        getIdentity: () => identity,
        getSources: () => [...observedSources.values()],
      })
    );
  }
  return workspaceRouterPromise;
}

async function renderWorkspaceRoute() {
  return (await getWorkspaceRouter()).render();
}

// ---------------------------------------------------------------- corpus + boot

// Desktop exposes conversation history by default; compact viewports protect the main
// task from being pushed below an open navigation panel. This only sets the initial
// disclosure state — after boot the user owns the control.
const conversationsPanel = $("conversations");
if (conversationsPanel) conversationsPanel.open = false;

wireCorpus({corpus: $("corpus"), body: $("corpus-body")});

loadIdentity()
  .then(async () => {
    if (!identity) return;
    declaration = restoreDeclaration();
    enterWorkingState();
    const route = await renderWorkspaceRoute();
    if (route?.id === "chat" || route?.id === "chat-conversation") query.focus({preventScroll:true});
    await loadInferenceStatus();
    if (!publicMode) await refreshBilling();
    const returned = new URLSearchParams(window.location.search).get("billing") === "return";
    if (returned) {
      $("subscription-pill").textContent = commerce?.active
        ? "Підписка активна"
        : "Платіж прийнято провайдером · очікую callback";
    }
  })
  .catch(() => { forgetIdentity("не автентифіковано"); void renderWorkspaceRoute(); });

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => undefined);
