import {
  ApiRefusal, call, clearBearerToken, escapeHtml, loginUrl, setBearerToken,
} from "./api.js";

const form = document.querySelector("#query-form");
const query = document.querySelector("#query");
const submit = document.querySelector("#submit");
const result = document.querySelector("#result");
const tokenInput = document.querySelector("#bearer-token");
const checkAuth = document.querySelector("#check-auth");
const login = document.querySelector("#login");
const logout = document.querySelector("#logout");
const identityState = document.querySelector("#identity-state");

async function loadIdentity() {
  identityState.textContent = "Перевірка…";
  const identity = await call("/v1/auth/me");
  identityState.innerHTML =
    `<strong>${escapeHtml(identity.subject)}</strong> · clearance ${escapeHtml(identity.clearance)} · ` +
    `${escapeHtml([...identity.roles].sort().join(", "))}`;
  login.hidden = true;
  logout.hidden = false;
  return identity;
}

function forgetIdentity(message) {
  clearBearerToken();
  login.hidden = false;
  logout.hidden = true;
  identityState.textContent = message;
}

checkAuth.addEventListener("click", async () => {
  setBearerToken(tokenInput.value);
  try {
    await loadIdentity();
    tokenInput.value = "";
  } catch (error) {
    forgetIdentity(`Відмова: ${error instanceof ApiRefusal ? error.reason : "невідома помилка"}`);
  }
});

login.addEventListener("click", () => {
  window.location.assign(loginUrl(window.location.pathname));
});

logout.addEventListener("click", async () => {
  try {
    await call("/v1/auth/logout", {method: "POST"});
    forgetIdentity("Не автентифіковано.");
  } catch (error) {
    identityState.textContent =
      `Logout відхилено: ${error instanceof ApiRefusal ? error.reason : "невідома помилка"}`;
  }
});

// A citation is the product. Rendering it as a quote with its authority, its edition and
// the span it came from is the difference between an answer a reader can check and an
// answer they have to trust — which is the whole claim this system makes.
function citationCard(citation) {
  const facts = [
    citation.page ? `с. ${escapeHtml(citation.page)}` : "",
    citation.authority ? escapeHtml(citation.authority) : "",
    citation.effective_from ? `чинний з ${escapeHtml(citation.effective_from)}` : "",
    `sha ${escapeHtml(String(citation.source_hash).slice(0, 12))}…`,
    `span ${escapeHtml(String(citation.span_id).slice(0, 8))}…`,
  ].filter(Boolean).map(fact => `<span>${fact}</span>`).join("");
  return `
    <article class="citation">
      <h3>${escapeHtml(citation.title)} · ред. ${escapeHtml(citation.revision)}</h3>
      <blockquote>${escapeHtml(citation.quote)}</blockquote>
      <div class="meta">${facts}</div>
    </article>`;
}

const STATUS_LABEL = {
  answered: ["Доказова відповідь", "answered"],
  insufficient_evidence: ["Недостатньо підстав", "withheld"],
  access_denied: ["Доступ не надано", "withheld"],
};

function render(answer) {
  const [heading, tone] = STATUS_LABEL[answer.status] ?? ["Відмова", "withheld"];
  const citations = (answer.citations ?? []).map(citationCard).join("");
  const limitations = (answer.limitations ?? [])
    .map(item => `<p class="limitation">${escapeHtml(item)}</p>`).join("");
  const heard = answer.status === "answered"
    ? ""
    : `<p class="limitation">Порожня відповідь не означає порожній корпус: вона означає, що ` +
      `чинного затвердженого джерела, доступного вашій ідентичності, для цього питання немає.</p>`;

  result.innerHTML = `
    <div class="verdict">
      <h2>${escapeHtml(heading)}</h2>
      <span class="chip ${tone}">${escapeHtml(answer.status)}</span>
    </div>
    <p class="answer-text">${escapeHtml(answer.text).replaceAll("\n", "<br>")}</p>
    ${heard}
    <dl class="metrics">
      <div><dt>Ranking utility</dt><dd>${Number(answer.retrieval_score).toFixed(3)}</dd></div>
      <div><dt>Evidence coverage</dt><dd>${Number(answer.evidence_coverage).toFixed(3)}</dd></div>
      <div><dt>Citations</dt><dd>${(answer.citations ?? []).length}</dd></div>
      <div><dt>Release</dt><dd>${escapeHtml(answer.corpus_release)}</dd></div>
    </dl>
    <p class="limitation">Ranking utility не є ймовірністю правильності.</p>
    ${citations}
    ${limitations ? `<div class="limitation standalone">${limitations}</div>` : ""}`;
  result.classList.remove("hidden", "error");
  result.scrollIntoView({block: "nearest", behavior: "smooth"});
}

async function ask() {
  submit.disabled = true;
  submit.textContent = "Перевірка…";
  result.classList.remove("hidden");
  result.classList.remove("error");
  result.innerHTML = `<p class="reason">Перевіряю корпус…</p>`;
  try {
    render(await call("/v1/answers", {method: "POST", body: {text: query.value}}));
  } catch (error) {
    // The API answers a withheld question with a reason. Collapsing it to "API 403"
    // discarded the only part the reader could act on.
    result.innerHTML =
      `<p class="refusal">${escapeHtml(
        error instanceof ApiRefusal ? `Відмова ${error.status}` : "Помилка")}</p>` +
      `<p class="reason">${escapeHtml(
        error instanceof ApiRefusal ? error.reason : "Невідома помилка")}</p>`;
    result.classList.add("error");
  } finally {
    submit.disabled = false;
    submit.textContent = "Знайти доказ";
  }
}

form.addEventListener("submit", event => {
  event.preventDefault();
  void ask();
});

// A multi-line field swallows Enter, so the only way to submit was to reach for the
// mouse on every question.
query.addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    if (form.reportValidity()) void ask();
  }
});

loadIdentity().catch(() => forgetIdentity("Не автентифіковано."));

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => undefined);
