const form = document.querySelector("#query-form");
const query = document.querySelector("#query");
const submit = document.querySelector("#submit");
const result = document.querySelector("#result");
const apiUrl = window.KORPUS_CONFIG?.apiUrl ?? "/api";
const tokenInput = document.querySelector("#bearer-token");
const checkAuth = document.querySelector("#check-auth");
const login = document.querySelector("#login");
const logout = document.querySelector("#logout");
const identityState = document.querySelector("#identity-state");
let bearerToken = "";

function readCookie(name) {
  const prefix = `${encodeURIComponent(name)}=`;
  const item = document.cookie.split("; ").find(value => value.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : "";
}

function authHeaders(extra = {}, method = "GET") {
  const headers = {...extra};
  if (bearerToken) headers.Authorization = `Bearer ${bearerToken}`;
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = readCookie("__Host-korpus_csrf");
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  return headers;
}

async function loadIdentity() {
  identityState.textContent = "Перевірка…";
  const response = await fetch(`${apiUrl}/v1/auth/me`, {
    headers: authHeaders(),
    credentials: "same-origin",
  });
  if (!response.ok) throw new Error(`API ${response.status}`);
  const identity = await response.json();
  identityState.textContent = `${identity.subject} · ${identity.clearance} · ${identity.roles.join(", ")}`;
  login.hidden = true;
  logout.hidden = false;
  return identity;
}

checkAuth.addEventListener("click", async () => {
  bearerToken = tokenInput.value.trim();
  try {
    await loadIdentity();
    tokenInput.value = "";
  } catch (error) {
    bearerToken = "";
    identityState.textContent = `Відмова: ${error instanceof Error ? error.message : "невідома помилка"}`;
  }
});

login.addEventListener("click", () => {
  window.location.assign(`${apiUrl}/v1/auth/login?return_to=${encodeURIComponent(window.location.pathname)}`);
});

logout.addEventListener("click", async () => {
  const response = await fetch(`${apiUrl}/v1/auth/logout`, {
    method: "POST",
    headers: authHeaders({}, "POST"),
    credentials: "same-origin",
  });
  if (response.ok) {
    bearerToken = "";
    login.hidden = false;
    logout.hidden = true;
    identityState.textContent = "Не автентифіковано.";
  } else {
    identityState.textContent = `Logout відхилено: API ${response.status}`;
  }
});

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
}

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
    const response = await fetch(`${apiUrl}/v1/answers`, {
      method: "POST",
      headers: authHeaders({"Content-Type":"application/json"}, "POST"),
      credentials: "same-origin",
      body: JSON.stringify({text: query.value})
    });
    if (!response.ok) throw new Error(`API ${response.status}`);
    render(await response.json());
  } catch (error) {
    result.innerHTML = `<h2>Помилка</h2><p>${escapeHtml(error instanceof Error ? error.message : "Невідома помилка")}</p>`;
    result.classList.remove("hidden");
    result.classList.add("error");
  } finally {
    submit.disabled = false;
    submit.textContent = "Знайти доказ";
  }
});

loadIdentity().catch(() => {
  login.hidden = false;
  logout.hidden = true;
  identityState.textContent = "Не автентифіковано.";
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => undefined);
