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
  ApiRefusal, NetworkError, call, clearBearerToken, escapeHtml, loginUrl, setBearerToken,
} from "./api.js";
import {askIn} from "./conversations.js";
import {
  forgetDeclaration, readDeclaration, rememberDeclaration, restoreDeclaration,
} from "./reader_declaration.js";
import {wireCorpus} from "./reader_corpus.js";
import {createConversationController} from "./reader_conversations.js";
import {UNFINISHED, VERDICT} from "./reader_verdicts.js";

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
//: In memory for the life of the tab, and mirrored to sessionStorage so it survives a
//: reload — a page eviction on a low-memory phone, an accidental refresh — without the
//: soldier retyping three fields under fire. NOT localStorage: the rule is that nothing
//: about a session outlives the tab, and a declaration that survives a shift change is a
//: declaration attributed to the wrong person. sessionStorage is exactly that boundary —
//: it is cleared when the tab closes, so a reload keeps it and the next person does not
//: inherit it.
let declaration = null;

// ---------------------------------------------------------------- identity

// On the public edge the visitor holds nothing: the edge attaches a read-only identity to
// every request, so a login button offers a flow that cannot complete and a token field
// invites pasting a credential into a page that has no use for one. Both are removed
// rather than disabled — a control that is visible and inert teaches the wrong thing
// about who is authenticated here.
const publicMode = Boolean(globalThis.window?.KORPUS_CONFIG?.publicMode);
const conversationController = createConversationController({publicMode, result, query});

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
  // The stored declaration is cleared with the identity: it belongs to the person who
  // authenticated, and a logout is exactly the shift change that must not carry it over.
  forgetDeclaration();
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
  void conversationController.start();
}

declarationForm.addEventListener("submit", async event => {
  event.preventDefault();
  const {declared, problems} = readDeclaration();
  if (!identity) {
    if (publicMode) {
      // On the public edge the identity comes from one /v1/auth/me the edge answers. A
      // single failed call at load — a dropped packet — otherwise leaves the page a dead
      // end for the whole session. Try once more before declaring the service down.
      try {
        await loadIdentity();
      } catch {
        // Still unreachable; fall through to the message with an action.
      }
    }
    if (!identity) {
      problems.unshift(
        publicMode
          ? {field: "identity-state",
             message: "Сервіс недоступний: особу не підтверджено. Перевірте зв'язок і спробуйте ще раз"}
          : {field: "bearer-token", message: "Спершу автентифікуйтесь"},
      );
    }
  }
  showErrors(problems);
  if (problems.length) return;
  declaration = rememberDeclaration(declared);
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

// Verdict vocabulary and unfinished-search reasons are centralized in reader_verdicts.js.

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
    // The same body either way. Inside a conversation the server records the question and
    // the answer; the transcript is never sent back with the next one, so nothing the
    // system said can become the evidence for what it says next.
    const body = {text: question, declaration};
    const conversation = await conversationController.forQuestion(question);
    const answer = conversation
      ? await askIn(conversation, body)
      : await call("/v1/answers", {method: "POST", body});
    pending.remove();
    render(answer, question);
    void conversationController.refresh();
    // Cleared only on success: a question that failed is still in the box, so the
    // reader retries rather than retypes.
    query.value = "";
  } catch (error) {
    pending.remove();
    // A lost link is the field's normal state, and it is a different message from a
    // refusal: the question was never asked, so nothing was decided about the corpus. The
    // question stays in the box — not cleared below — so the soldier retries, not retypes.
    if (error instanceof NetworkError) {
      const offlineBlock = document.createElement("article");
      offlineBlock.className = "turn";
      offlineBlock.innerHTML =
        `<p class="turn-question"><span class="turn-mark" aria-hidden="true"></span>${
          escapeHtml(question)}</p>` +
        `<div class="verdict denied"><span class="verdict-mark" aria-hidden="true"></span>` +
        `<h2>${escapeHtml(error.offline ? "НЕМАЄ ЗВ'ЯЗКУ" : "ЗВ'ЯЗОК ПЕРЕРВАВСЯ")}</h2></div>` +
        `<p class="answer-text">Питання не надіслано і лишилось у полі. Перевірте зв'язок і
         натисніть «Знайти доказ» ще раз — нічого набирати заново не треба.</p>`;
      result.append(offlineBlock);
      offlineBlock.scrollIntoView({block: "nearest", behavior: "smooth"});
      return;
    }
    // The API answers a withheld question with a reason. Collapsing it to a status code
    // discards the only part the reader can act on.
    const refusal = error instanceof ApiRefusal ? error : null;
    // 402 is not a refusal about the corpus and must not read like one. "ПІДСТАВИ НЕМАЄ"
    // tells a reader the manuals are silent on their question; a lapsed subscription tells
    // them nothing about the manuals at all, and confusing the two sends somebody away
    // from a rule that exists.
    const paywalled = refusal?.status === 402;
    const heading = paywalled
      ? "ПОТРІБНА ПІДПИСКА"
      : refusal ? `ВІДМОВА ${refusal.status}` : "ПОМИЛКА";
    const detail = refusal?.payload?.detail;
    const reason = typeof detail === "object" && detail !== null
      ? String(detail.detail ?? detail.reason ?? refusal.reason)
      : refusal?.reason ?? "Невідома помилка";
    const block = document.createElement("article");
    block.className = "turn";
    block.innerHTML =
      `<p class="turn-question"><span class="turn-mark" aria-hidden="true"></span>${
        escapeHtml(question)}</p>` +
      `<div class="verdict ${paywalled ? "withheld" : "denied"}">` +
      `<span class="verdict-mark" aria-hidden="true"></span>` +
      `<h2>${escapeHtml(heading)}</h2></div>` +
      `<p class="answer-text">${escapeHtml(reason)}</p>` +
      (paywalled
        ? `<p class="note">Це не відповідь про корпус: про наявність чи відсутність
           підстави нічого не сказано. Доступ до цього розділу не оплачено.</p>`
        : "");
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

const corpus = $("corpus");
const corpusBody = $("corpus-body");
wireCorpus({corpus, body: corpusBody});

// On load: confirm the identity, then — only if a declaration from before a reload is
// still valid — walk straight back to the ask screen so a refresh does not cost the
// soldier the three fields again. The restore happens after identity so a stored
// declaration can never stand in for authentication.
loadIdentity()
  .then(() => {
    if (!identity) return;
    const restored = restoreDeclaration();
    if (restored) {
      declaration = restored;
      enterWorkingState();
    }
  })
  .catch(() => forgetIdentity("не автентифіковано"));

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => undefined);
