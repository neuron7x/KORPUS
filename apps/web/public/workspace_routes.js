import {call, describeError} from "./api.js";
import {PACK_STATE} from "./offline_pack.js";
import {createOfflineController} from "./offline_controller.js";
import {resolveRoute, routeAccess} from "./routes.js";

function ensureWorkspaceStyles() {
  if (document.querySelector('link[data-korpus-workspace-styles]')) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = "/workspace.css";
  link.dataset.korpusWorkspaceStyles = "true";
  document.head.append(link);
}

function node(tag, text = "", className = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function setCurrentNavigation(nav, route, bootstrap, authenticated) {
  for (const link of nav?.querySelectorAll("[data-route-link]") ?? []) {
    const target = resolveRoute(link.getAttribute("href") ?? "");
    const access = routeAccess(target, authenticated, bootstrap);
    link.hidden = !access.allowed;
    const current = access.allowed && target && (target.id === route.id || (route.id === "chat-conversation" && target.id === "chat"));
    if (current) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

function renderState(view, title, state, detail = "") {
  view.replaceChildren();
  const heading = node("h2", title, "route-title");
  view.append(heading);
  const status = node("p", detail || state, `route-state route-${state}`);
  status.setAttribute("role", state === "error" ? "alert" : "status");
  view.append(status);
}

function renderRouteError(view, title, error, retry) {
  const copy = describeError(error, "Розділ не вдалося завантажити.");
  renderState(view, title, "error", copy.message);
  const button = node("button", "Повторити", "secondary route-action");
  button.type = "button";
  button.addEventListener("click", () => void retry());
  view.append(button);
}

function renderDocuments(view, documents) {
  renderState(view, "Документи", documents.length ? "success" : "empty", documents.length ? `${documents.length} доступних документів` : "Доступних документів немає.");
  if (!documents.length) return;
  const list = node("ul", "", "route-list");
  for (const item of documents) {
    const row = node("li", "", "route-card");
    row.append(node("strong", String(item.canonical_title ?? "Без назви")));
    row.append(node("span", `${item.issuer ?? "—"} · ${item.corpus_id ?? "—"} · рівень ${item.access_tier ?? "—"}`));
    list.append(row);
  }
  view.append(list);
}

function renderKnowledge(view, documents) {
  const grouped = new Map();
  for (const item of documents) grouped.set(item.corpus_id, (grouped.get(item.corpus_id) ?? 0) + 1);
  renderState(view, "База знань", grouped.size ? "success" : "empty", grouped.size ? `${grouped.size} доступних корпусів` : "Доступних корпусів немає.");
  if (!grouped.size) return;
  const list = node("dl", "", "route-metrics");
  for (const [corpus, count] of [...grouped].sort(([a], [b]) => String(a).localeCompare(String(b)))) {
    list.append(node("dt", String(corpus)), node("dd", `${count} документів`));
  }
  view.append(list);
}

function renderSources(view, sources) {
  renderState(view, "Джерела цієї сесії", sources.length ? "success" : "empty", sources.length ? `${sources.length} цитованих джерел` : "Ще немає цитованих джерел. Джерело з’явиться тут після відповіді, підтвердженої доказом.");
  if (!sources.length) return;
  const list = node("ul", "", "route-list");
  for (const source of sources) {
    const row = node("li", "", "route-card");
    row.append(node("strong", `${source.title} · ред. ${source.revision}`));
    row.append(node("span", `фрагмент ${String(source.span_id).slice(0, 12)}… · SHA ${String(source.source_hash).slice(0, 12)}…`));
    const open = node("button", "Відкрити точний фрагмент", "secondary route-action");
    open.type = "button";
    open.dataset.openSpan = String(source.span_id);
    open.dataset.versionId = String(source.version_id);
    row.append(open);
    list.append(row);
  }
  view.append(list);
}

function renderProfile(view, bootstrap) {
  const identity = bootstrap?.identity ?? {};
  const capabilities = bootstrap?.capabilities ?? {};
  renderState(view, "Профіль", "success", "Підтверджена сервером ідентичність і чинні правила доступу");
  const list = node("dl", "", "route-metrics");
  const values = [
    ["Обліковий ідентифікатор", identity.subject],
    ["Рівень допуску", identity.clearance],
    ["Ролі", (identity.roles ?? []).join(", ") || "—"],
    ["Корпуси", (identity.corpora ?? []).join(", ") || "—"],
    ["Дозволи", (bootstrap?.effective_permissions ?? []).join(", ") || "—"],
    ["Версія системи", bootstrap?.release],
    ["Версія API", bootstrap?.api_version],
    ["Режим завантаження", capabilities.ingestion_mode],
    ["Офлайн-доступ", capabilities.offline_pack_enabled ? "увімкнено" : "вимкнено"],
    ["Підписка", capabilities.subscription_required ? "обов’язкова" : "не обов’язкова"],
  ];
  for (const [key, value] of values) list.append(node("dt", key), node("dd", String(value ?? "—")));
  view.append(list);
}

function renderOffline(view, validation, actions) {
  const state = validation?.state ?? PACK_STATE.ABSENT;
  const safe = state === PACK_STATE.VALID;
  renderState(view, "Офлайн-пакет", safe ? "success" : "empty", `${state} · ${validation?.reason ?? "пакет не завантажено"}`);
  view.append(node("p", safe
    ? "Офлайн-відповідь дозволена лише в межах підписаного, чинного та scope-сумісного пакета."
    : "Офлайн-відповіді заблоковані. Браузер не має секрету для самопідпису і не може сам собі видати PACK_VALID.", "route-note"));
  const refresh = node("button", "Оновити підписаний пакет", "secondary route-action");
  refresh.type = "button";
  refresh.addEventListener("click", () => void actions.refresh());
  view.append(refresh);
  if (state !== PACK_STATE.ABSENT) {
    const clear = node("button", "Видалити локальний пакет", "secondary route-action");
    clear.type = "button";
    clear.addEventListener("click", () => void actions.clear());
    view.append(clear);
  }
}

function renderAuditForm(view, onSubmit) {
  renderState(view, "Аудит запиту", "empty", "Введіть ідентифікатор запиту. Читання аудиту потребує підтвердженого дозволу.");
  const form = node("form", "", "route-form");
  const label = node("label", "Ідентифікатор запиту");
  label.htmlFor = "audit-trace-id";
  const input = node("input");
  input.id = "audit-trace-id";
  input.name = "trace_id";
  input.required = true;
  input.minLength = 1;
  input.maxLength = 128;
  input.autocomplete = "off";
  const button = node("button", "Прочитати аудит", "secondary");
  button.type = "submit";
  form.append(label, input, button);
  form.addEventListener("submit", event => {
    event.preventDefault();
    const trace = input.value.trim();
    if (trace) void onSubmit(trace);
  });
  view.append(form);
}

function renderAuditEvents(view, trace, events) {
  renderState(view, "Аудит запиту", events.length ? "success" : "empty", events.length ? `${events.length} подій · запит ${trace}` : `Подій для запиту ${trace} не знайдено.`);
  if (!events.length) return;
  const list = node("ol", "", "route-list");
  for (const event of events) {
    const row = node("li", "", "route-card");
    row.append(node("strong", String(event.action ?? "audit event")));
    row.append(node("span", `${event.occurred_at ?? "—"} · seq ${event.sequence ?? "—"}`));
    row.append(node("span", `event ${String(event.event_hash ?? "—").slice(0, 16)}… · prev ${String(event.previous_hash ?? "—").slice(0, 16)}… · key ${event.audit_key_id ?? "—"}`));
    list.append(row);
  }
  view.append(list);
}

export function createWorkspaceRouter({view, nav, chatNodes, isAuthenticated, getBootstrap, getIdentity, getSources}) {
  if (!view) throw new Error("route view is required");
  ensureWorkspaceStyles();
  const offline = createOfflineController({getIdentity});
  let current = null;
  let renderEpoch = 0;

  function showChat(show) {
    for (const item of chatNodes ?? []) item.hidden = !show;
    view.hidden = show;
  }

  async function render(pathname = window.location.pathname) {
    const epoch = ++renderEpoch;
    let route = resolveRoute(pathname);
    if (pathname === "/" && route?.path === "/chat") window.history.replaceState({}, "", "/chat");
    const authenticated = Boolean(isAuthenticated?.());
    const bootstrap = getBootstrap?.() ?? null;
    const access = routeAccess(route, authenticated, bootstrap);
    if (!access.allowed) {
      const destination = access.redirect;
      if (window.location.pathname !== destination) window.history.replaceState({}, "", destination);
      route = resolveRoute(destination);
    }
    current = route;
    setCurrentNavigation(nav, route, bootstrap, authenticated);
    const isChat = route?.id === "chat" || route?.id === "chat-conversation";
    showChat(isChat);
    if (isChat) return route;
    view.hidden = false;

    try {
      switch (route?.id) {
        case "login":
          renderState(view, "Вхід", "empty", isAuthenticated?.() ? "Сесію вже підтверджено сервером." : "Продовжте через захищений вхід. Локально вказана роль не надає доступу.");
          break;
        case "documents": {
          renderState(view, "Документи", "loading", "Завантаження…");
          const data = await call("/v1/documents");
          if (epoch === renderEpoch) renderDocuments(view, Array.isArray(data) ? data : []);
          break;
        }
        case "knowledge": {
          renderState(view, "База знань", "loading", "Завантаження…");
          const data = await call("/v1/documents");
          if (epoch === renderEpoch) renderKnowledge(view, Array.isArray(data) ? data : []);
          break;
        }
        case "sources":
          renderSources(view, getSources?.() ?? []);
          break;
        case "offline":
          renderOffline(view, await offline.state(), {
            refresh: async () => { await offline.exportFresh(); await render("/offline"); },
            clear: async () => { await offline.clear(); await render("/offline"); },
          });
          break;
        case "audit":
          renderAuditForm(view, async trace => {
            renderState(view, "Аудит запиту", "loading", "Перевіряю серверний ланцюг аудиту…");
            try {
              const events = await call(`/v1/audit/events?trace_id=${encodeURIComponent(trace)}&limit=100`);
              renderAuditEvents(view, trace, Array.isArray(events) ? events : []);
            } catch (error) {
              renderRouteError(view, "Аудит запиту", error, () => render("/audit"));
            }
          });
          break;
        case "profile":
          renderState(view, "Профіль", "loading", "Перевірка серверної ідентичності…");
          renderProfile(view, bootstrap);
          break;
        case "access-denied":
          renderState(view, "Доступ заборонено", "error", "Маршрут не існує або поточна сесія не має права його відкрити.");
          break;
        default:
          renderState(view, "Доступ заборонено", "error", "Невідомий маршрут.");
      }
    } catch (error) {
      if (epoch !== renderEpoch) return route;
      renderRouteError(view, route?.id ?? "Маршрут", error, () => render(pathname));
    }
    return route;
  }

  function navigate(path, {replace = false} = {}) {
    const route = resolveRoute(path);
    const target = route?.path ?? "/access-denied";
    if (replace) window.history.replaceState({}, "", target);
    else window.history.pushState({}, "", target);
    return render(target);
  }

  nav?.addEventListener("click", event => {
    const link = event.target.closest?.("a[data-route-link]");
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const disclosure = link.closest(".mobile-more");
    if (disclosure) disclosure.open = false;
    void navigate(link.getAttribute("href") ?? "/access-denied");
  });
  window.addEventListener("popstate", () => { void render(); });

  return Object.freeze({render, navigate, get current() { return current; }});
}
