const form = document.querySelector("#query-form");
const query = document.querySelector("#query");
const submit = document.querySelector("#submit");
const result = document.querySelector("#result");
const apiUrl = window.KORPUS_CONFIG?.apiUrl ?? "/api";

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
      <div><dt>Retrieval</dt><dd>${Number(answer.retrieval_score).toFixed(3)}</dd></div>
      <div><dt>Evidence</dt><dd>${Number(answer.evidence_coverage).toFixed(3)}</dd></div>
      <div><dt>Release</dt><dd>${escapeHtml(answer.corpus_release)}</dd></div>
    </dl>${citations}${limitations}`;
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
      headers: {"Content-Type":"application/json"},
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

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => undefined);
