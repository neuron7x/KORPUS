const clamp = value => Math.max(0, Math.min(1, Number.isFinite(Number(value)) ? Number(value) : 0));

const DECISION = Object.freeze({
  answered: ["ДОПУЩЕНО", "admitted", "Вердикт зміниться, якщо чинність джерела буде скасована або з’явиться авторитетний суперечний доказ."],
  insufficient_evidence: ["НЕ ДОПУЩЕНО", "withheld", "Потрібен чинний фрагмент, який прямо покриває запит. Подібність тексту без підстави рішення не змінює."],
  requires_human_review: ["КОНФЛІКТ", "review", "Потрібно визначити пріоритет редакцій або авторитетних джерел. Система не обирає зручну версію сама."],
  access_denied: ["ЗА МЕЖЕЮ ДОПУСКУ", "denied", "Потрібен серверно підтверджений допуск до відповідного корпусу; заявлений контекст права не розширює."],
});

function sourceNode(citation, index) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "field-source";
  button.dataset.sourceIndex = String(index);
  button.innerHTML = `<span>0${index + 1}</span><strong></strong><small></small><i aria-hidden="true"></i>`;
  button.querySelector("strong").textContent = citation.title || "Джерело без назви";
  button.querySelector("small").textContent = `ред. ${citation.revision || "—"} · ${String(citation.source_hash || "без-суми").slice(0, 8)}`;
  button.addEventListener("click", () => {
    const target = document.querySelector(`[data-open-span="${CSS.escape(String(citation.span_id))}"]`)?.closest(".citation");
    if (!target) return;
    target.dataset.commandFocus = "true";
    target.scrollIntoView({behavior: "smooth", block: "center"});
    target.addEventListener("animationend", () => delete target.dataset.commandFocus, {once:true});
  });
  return button;
}

function mountStyles() {
  if (document.getElementById("decision-field-styles")) return;
  const link = document.createElement("link");
  Object.assign(link, {id: "decision-field-styles", rel: "stylesheet", href: "/decision_field.css"});
  document.head.append(link);
}

export function createDecisionField(answer) {
  mountStyles();
  const citations = Array.isArray(answer.citations) ? answer.citations : [];
  const limitations = Array.isArray(answer.limitations) ? answer.limitations : [];
  // Шкала показувала `evidence_coverage` як «% доказу». Це число дорівнює 1.000 у
  // КОЖНІЙ відповіді (кожен claim будується з цитованого спана — тавтологія за
  // побудовою) і, за паралельним виміром 31.08.2026, ВИЩЕ на хибних відповідях, ніж на
  // правильних. Найбільша цифра на екрані означала протилежне обіцяному.
  //
  // Тепер шкала показує частку цитат, які витримали присуд НЕЗАЛЕЖНИХ осей. Вона вміє
  // бути неповною, і саме тому їй можна вірити.
  const verdicts = citations.map(citation => citation.presentation ?? "supported");
  const supported = verdicts.filter(verdict => verdict === "supported").length;
  const coverage = clamp(verdicts.length ? supported / verdicts.length : 0);
  const [label, tone, counterfactual] = DECISION[answer.status] ?? ["ЗУПИНЕНО", "withheld", "Потрібен новий серверний вердикт із повним доказовим маршрутом."];
  const field = document.createElement("details");
  field.className = "decision-field";
  field.dataset.tone = tone;
  field.setAttribute("aria-label", "Карта підстави рішення");
  field.innerHTML = `
    <summary class="field-summary"><span>ПІДСТАВА РІШЕННЯ</span><strong>${label}</strong><b>${Math.round(coverage * 100)}% підтверджено</b></summary>
    <div class="field-detail"><header class="field-head"><div><span>ПІДСТАВА / ПОХОДЖЕННЯ ДОКАЗУ</span><h3>Карта підстави рішення</h3></div><b>НЕ ЙМОВІРНІСТЬ</b></header>
    <div class="field-grid">
      <div class="field-core">
        <svg viewBox="0 0 120 120" role="img" aria-label="Підтверджено незалежними осями: ${Math.round(coverage * 100)} відсотків">
          <circle class="field-track" cx="60" cy="60" r="51"></circle><circle class="field-value" cx="60" cy="60" r="51"></circle>
        </svg>
        <div><span>СЕРВЕРНИЙ ВЕРДИКТ</span><strong>${label}</strong><small>${Math.round(coverage * 100)}% витримало присуд осей</small></div>
      </div>
      <div class="field-sources" aria-label="Допущені джерела"></div>
      <dl class="field-invariants">
        <div><dt>ПІДСТАВА</dt><dd>${citations.length ? "ПРИВ’ЯЗАНО ДО ДЖЕРЕЛА" : "НЕМАЄ"}</dd></div>
        <div><dt>ПРИСУД ОСЕЙ</dt><dd>${supported}/${citations.length} ПІДТВЕРДЖЕНО</dd></div>
        <div><dt>ОБМЕЖЕННЯ</dt><dd>${limitations.length || "НЕМАЄ"}</dd></div>
        <div><dt>ВЕРСІЯ</dt><dd></dd></div>
      </dl>
    </div>
    <details class="field-counterfactual"><summary><span>УМОВА ЗМІНИ</span> Що змінить цей вердикт?</summary><p></p></details></div>`;
  field.querySelector(".field-value").setAttribute("stroke-dasharray", `${coverage * 320.5} 320.5`);
  field.querySelector(".field-invariants div:last-child dd").textContent = answer.corpus_release || "НЕ ПРИВ’ЯЗАНО";
  field.querySelector(".field-counterfactual p").textContent = counterfactual;
  const sourceList = field.querySelector(".field-sources");
  citations.slice(0, 6).forEach((citation, index) => sourceList.append(sourceNode(citation, index)));
  if (!citations.length) {
    const empty = document.createElement("p");
    empty.className = "field-empty";
    empty.textContent = "Жодного фрагмента не допущено до підстави.";
    sourceList.append(empty);
  }
  return field;
}
