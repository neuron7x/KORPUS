import {call, escapeHtml} from "./api.js";

const $ = id => document.getElementById(id);

function copyable(value, shorten = true) {
  const shown = shorten ? `${String(value).slice(0, 8)}…` : String(value);
  return `<button type="button" class="copyable" data-copy="${escapeHtml(value)}" ` +
    `title="${escapeHtml(value)} — натисніть, щоб скопіювати">${escapeHtml(shown)}</button>`;
}

function renderDocuments(target, documents) {
  target.classList.remove("error");
  if (!documents.length) {
    target.innerHTML =
      `<h4>Документи</h4><p class="reason">Жодного документа не доступно вашій ідентичності. ` +
      `Це не означає, що корпус порожній.</p>`;
    return;
  }
  const rows = documents.map(record => `
    <tr>
      <td>${escapeHtml(record.canonical_title)}</td>
      <td>${escapeHtml(record.issuer)}</td>
      <td>${escapeHtml(record.corpus_id)}</td>
      <td>${escapeHtml(record.classification)} · рівень ${escapeHtml(record.access_tier)}</td>
      <td>${copyable(record.id)}</td>
    </tr>`).join("");
  target.innerHTML =
    `<h4>Документи (${documents.length})</h4>` +
    `<div class="table-scroll"><table>` +
    `<caption>Доступні вашій ідентичності. Натисніть на ідентифікатор, щоб скопіювати.</caption>` +
    `<thead><tr><th>Назва</th><th>Видавець</th><th>Корпус</th><th>Класифікація</th><th>Ідентифікатор</th></tr></thead>` +
    `<tbody>${rows}</tbody></table></div>`;
}

function renderSpans(target, spans, asOf) {
  target.classList.remove("error");
  const when = asOf || "сьогодні";
  if (!spans.length) {
    target.innerHTML =
      `<h4>Фрагменти</h4><p class="reason">Жодного фрагмента не доступно вашій ідентичності ` +
      `станом на ${escapeHtml(when)}. Це може означати, що версія не чинна на цю дату, ` +
      `а не що вона порожня.</p>`;
    return;
  }
  const items = spans.map(span => `
    <article class="span-item">
      <h5>№${escapeHtml(span.ordinal)}${span.page ? ` · с.${escapeHtml(span.page)}` : ""}${
        span.section ? ` · ${escapeHtml(span.section)}` : ""}</h5>
      <p>${escapeHtml(span.text)}</p>
      ${copyable(span.span_id)}
    </article>`).join("");
  target.innerHTML = `<h4>Фрагменти (${spans.length}) станом на ${escapeHtml(when)}</h4>${items}`;
}

const JOB_STATE = {
  queued: ["wait", "У черзі: ще не бралося в роботу"],
  running: ["wait", "Виконується"],
  succeeded: ["ok", "Виконано: версія в карантині й чекає на рецензента"],
  retryable: ["wait", "Помилка, буде повторено"],
  dead_letter: ["bad", "Вичерпано спроби: потрібне рішення оператора"],
};

function renderJob(target, job) {
  target.classList.remove("error");
  const [tone, label] = JOB_STATE[job.state] ?? ["bad", "Стан невідомий"];
  const detail = job.error_detail ? `<p class="reason">${escapeHtml(job.error_detail)}</p>` : "";
  target.innerHTML =
    `<h4>Завдання ${escapeHtml(job.kind ?? "")}</h4>` +
    `<p class="status-line"><span class="dot ${tone}"></span>${escapeHtml(label)}</p>` +
    `<p class="reason">Спроб: ${escapeHtml(job.attempts)} з ${escapeHtml(job.max_attempts)}.</p>` +
    detail + `<pre>${escapeHtml(JSON.stringify(job, null, 2))}</pre>`;
  target.classList.toggle("error", tone === "bad");
}

function renderAuditVerification(target, verification) {
  const intact = Boolean(verification.valid);
  const anchor = verification.anchor_pending
    ? `Зовнішній якір позаду голови на ${escapeHtml(verification.anchor_pending)} подій: ` +
      `недоставлена робота, а не порушення.`
    : "Зовнішній якір узгоджений з головою ланцюга.";
  const broken = intact ? "" : `<p class="reason">Перша невідповідність: послідовність ` +
    `${escapeHtml(verification.first_invalid_sequence ?? "?")}. Причина: ` +
    `${escapeHtml(verification.reason ?? "не вказано")}.</p>`;
  target.innerHTML =
    `<h4>Ланцюг аудиту</h4>` +
    `<p class="status-line"><span class="dot ${intact ? "ok" : "bad"}"></span>` +
    `${intact ? "Ланцюг цілісний" : "Ланцюг порушено"}</p>` +
    `<p class="reason">Подій: ${escapeHtml(verification.event_count)}. ${anchor}</p>` +
    broken + `<pre>${escapeHtml(JSON.stringify(verification, null, 2))}</pre>`;
  target.classList.toggle("error", !intact);
}

function renderEvents(target, events) {
  target.classList.remove("error");
  if (!events.length) {
    target.innerHTML =
      `<h4>Події трасування</h4><p class="reason">Подій із таким trace id немає. ` +
      `Trace id живе в заголовку відповіді запиту, який ви розслідуєте.</p>`;
    return;
  }
  const rows = events.map(event => `
    <tr>
      <td><code>${escapeHtml(event.sequence ?? "")}</code></td>
      <td>${escapeHtml(event.occurred_at ?? "")}</td>
      <td>${escapeHtml(event.actor_subject ?? "")}</td>
      <td>${escapeHtml(event.action ?? "")}</td>
      <td>${escapeHtml(event.resource_type ?? "")}</td>
    </tr>`).join("");
  target.innerHTML =
    `<h4>Події трасування (${events.length})</h4>` +
    `<div class="table-scroll"><table>` +
    `<caption>Послідовність, мить, суб’єкт, дія, ресурс.</caption>` +
    `<thead><tr><th>№</th><th>Час</th><th>Суб’єкт</th><th>Дія</th><th>Ресурс</th></tr></thead>` +
    `<tbody>${rows}</tbody></table></div>`;
}

export function wireReadOnly({busy, renderProblems, renderRefusal}) {
  $("job-form").addEventListener("submit", async event => {
    event.preventDefault();
    const target = $("job-result");
    const jobId = $("job-id").value.trim();
    if (!jobId) return renderProblems(target, ["ідентифікатор завдання: обов'язковий"]);
    busy(target, "Читаю стан…");
    try { renderJob(target, await call(`/v1/ingestion-jobs/${encodeURIComponent(jobId)}`)); }
    catch (error) { renderRefusal(target, error); }
  });

  $("spans-form").addEventListener("submit", async event => {
    event.preventDefault();
    const target = $("spans-result");
    const versionId = $("spans-version-id").value.trim();
    if (!versionId) return renderProblems(target, ["ідентифікатор версії: обов'язковий"]);
    const asOf = $("spans-as-of").value;
    const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : "";
    busy(target, "Читаю фрагменти…");
    try {
      renderSpans(target, await call(`/v1/document-versions/${encodeURIComponent(versionId)}/spans${query}`), asOf);
    } catch (error) { renderRefusal(target, error); }
  });

  $("documents-refresh").addEventListener("click", async () => {
    const target = $("documents-result");
    busy(target, "Читаю перелік…");
    try { renderDocuments(target, await call("/v1/documents")); }
    catch (error) { renderRefusal(target, error); }
  });

  $("audit-verify").addEventListener("click", async () => {
    const target = $("audit-verify-result");
    busy(target, "Перевіряю ланцюг…");
    try { renderAuditVerification(target, await call("/v1/audit/verify")); }
    catch (error) { renderRefusal(target, error); }
  });

  $("audit-events-form").addEventListener("submit", async event => {
    event.preventDefault();
    const target = $("audit-events-result");
    const trace = $("audit-trace").value.trim();
    if (!trace) return renderProblems(target, ["trace id: обов'язковий"]);
    const limit = Number($("audit-limit").value) || 200;
    busy(target, "Читаю події…");
    try {
      renderEvents(target, await call(`/v1/audit/events?trace_id=${encodeURIComponent(trace)}&limit=${limit}`));
    } catch (error) { renderRefusal(target, error); }
  });
}
