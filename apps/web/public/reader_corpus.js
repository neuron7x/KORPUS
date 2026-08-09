import {ApiRefusal, call, escapeHtml} from "./api.js";

export function groupByType(documents) {
  const groups = new Map();
  for (const document_ of documents) {
    const key = document_.document_type || "без розділу";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(document_);
  }
  return [...groups.entries()].sort((left, right) => right[1].length - left[1].length);
}

export function renderCorpus(body, documents) {
  if (!documents.length) {
    body.innerHTML = `<p class="note">Корпус порожній для вашого допуску.</p>`;
    return;
  }
  const groups = groupByType(documents);
  body.innerHTML =
    `<p class="corpus-total"><strong>${documents.length}</strong> документів · ` +
    `<strong>${groups.length}</strong> розділів · доступних вашому допуску</p>` +
    groups.map(([type, items]) =>
      `<details class="corpus-group"><summary>${escapeHtml(type)} ` +
      `<span class="corpus-count">${items.length}</span></summary><ul>${
        items.slice(0, 200).map(item =>
          `<li>${escapeHtml(item.canonical_title)}</li>`).join("")
      }${
        items.length > 200 ? `<li class="note">…і ще ${items.length - 200}</li>` : ""
      }</ul></details>`).join("");
}

export function wireCorpus({corpus, body}) {
  let loaded = false;
  corpus.addEventListener("toggle", () => {
    if (!corpus.open || loaded) return;
    loaded = true;
    call("/v1/documents")
      .then(documents => renderCorpus(body, documents))
      .catch(error => {
        loaded = false;
        body.innerHTML = `<p class="note">Перелік недоступний: ${escapeHtml(
          error instanceof ApiRefusal ? error.reason : "невідома помилка")}</p>`;
      });
  });
}
