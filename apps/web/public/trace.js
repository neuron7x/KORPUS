const COPY = Object.freeze({
  query: "Сформулюйте одну перевірювану дію, норму або твердження.",
  access: "Сервер перевіряє ідентичність, допуск і корпус до початку пошуку.",
  evidence: "Пошук допускає лише чинні фрагменти доступних контрольованих джерел.",
  verdict: "Відповідь виходить із цитатою або явно зупиняється — правдоподібного fallback немає.",
});

const PROGRESS = Object.freeze({
  UNAUTHENTICATED: [-1, "Потрібна підтверджена сесія."], READY: [0, "Готовий прийняти точний запит."],
  QUERY_SUBMITTED: [0, "Запит прийнято без зміни його змісту."], POLICY_CHECK: [1, "Сервер перевіряє допуск перед пошуком."],
  ACCESS_DENIED: [3, "Маршрут зупинено політикою доступу."], RETRIEVING: [2, "Пошук перевіряє доступні фрагменти."],
  NO_EVIDENCE: [3, "Достатнього доказу не допущено."], EVIDENCE_FOUND: [2, "Доказ знайдено; формується вердикт."],
  CONFLICT: [3, "Джерела суперечать одне одному — потрібна перевірка."], COMPOSING: [3, "Формулювання обмежене допущеними цитатами."],
  ANSWER_READY: [3, "Вердикт сформовано з доказу."], AUDIT_COMMIT: [3, "Маршрут фіксується в аудиті."],
  COMPLETE: [4, "Маршрут завершено й зафіксовано."], FAIL_CLOSED: [3, "Контур безпечно зупинено без твердження."],
});

export function createTraceController(root = document) {
  const surface = root.getElementById("evidence-trace");
  surface.innerHTML = `<summary><span>KORPUS TRACE</span><strong id="trace-status" role="status" aria-live="polite">Готовий до перевірки</strong></summary><div class="trace-body"><ol class="trace-path" aria-label="Маршрут доказової відповіді">${[["query","ЗАПИТ"],["access","ДОПУСК"],["evidence","ДОКАЗ"],["verdict","ВЕРДИКТ"]].map(([key,label],index)=>`<li><button type="button" data-trace-stage="${key}"><b>0${index+1}</b><span>${label}</span></button></li>`).join("")}</ol><p id="trace-explainer" class="trace-explainer">${COPY.query}</p></div>`;
  const status = root.getElementById("trace-status");
  const explainer = root.getElementById("trace-explainer");
  const stages = [...root.querySelectorAll("[data-trace-stage]")];
  for (const button of stages) button.addEventListener("click", () => {
    for (const stage of stages) stage.setAttribute("aria-pressed", String(stage === button));
    explainer.textContent = COPY[button.dataset.traceStage];
  });
  return Object.freeze({
    render(state) {
      const progress = PROGRESS[state] ?? [-1, "Стан контуру не визначено."];
      status.textContent = progress[1];
      if (!["READY", "COMPLETE"].includes(state)) surface.open = true;
      stages.forEach((button, index) => {
        button.dataset.state = index < progress[0] ? "done" : index === progress[0] ? "active" : "idle";
        if (index === progress[0]) button.setAttribute("aria-current", "step"); else button.removeAttribute("aria-current");
      });
    },
  });
}
