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
  identityState.textContent = `${identity.subject} · ${identity.clearance} · ${[...identity.roles].join(", ")}`;
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

function render(answer) {
  const citations = (answer.citations ?? []).map(citation => `
    <article class="citation">
      <h3>${escapeHtml(citation.title)} · rev ${escapeHtml(citation.revision)}${citation.page ? ` · p.${citation.page}` : ""}</h3>
      <blockquote>${escapeHtml(citation.quote)}</blockquote>
      <code>${escapeHtml(citation.source_hash.slice(0,20))}… / ${escapeHtml(citation.span_id)}</code>
    </article>`).join("");
  const limitations = (answer.limitations ?? []).map(item => `<p class="limitation">${escapeHtml(item)}</p>`).join("");
  result.innerHTML = `
    <div class="answerHead"><h2>${answer.status === "answered" ? "Доказова відповідь" : "Відмова"}</h2><span>${escapeHtml(answer.status)}</span></div>
    <div class="answerText">${escapeHtml(answer.text).replaceAll("\n", "<br>")}</div>
    <dl class="metrics">
      <div><dt>Ranking utility</dt><dd>${Number(answer.retrieval_score).toFixed(3)}</dd></div>
      <div><dt>Evidence coverage</dt><dd>${Number(answer.evidence_coverage).toFixed(3)}</dd></div>
      <div><dt>Release</dt><dd>${escapeHtml(answer.corpus_release)}</dd></div>
    </dl><p class="limitation">Ranking utility не є ймовірністю правильності.</p>${citations}${limitations}`;
  result.classList.remove("hidden", "error");
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  submit.disabled = true;
  submit.textContent = "Перевірка…";
  result.classList.add("hidden");
  try {
    render(await call("/v1/answers", {method: "POST", body: {text: query.value}}));
  } catch (error) {
    // The API answers a withheld question with a reason. Collapsing it to "API 403"
    // discarded the only part the reader could act on.
    result.innerHTML = `<h2>Помилка</h2><p>${escapeHtml(
      error instanceof ApiRefusal ? `${error.status} · ${error.reason}` : "Невідома помилка"
    )}</p>`;
    result.classList.remove("hidden");
    result.classList.add("error");
  } finally {
    submit.disabled = false;
    submit.textContent = "Знайти доказ";
  }
});

loadIdentity().catch(() => forgetIdentity("Не автентифіковано."));

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => undefined);
