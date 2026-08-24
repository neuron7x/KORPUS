import {ApiRefusal, NetworkError, call} from "./api.js";
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

function renderDocuments(view, documents) {
  renderState(view, "Документи", documents.length ? "success" : "empty", documents.length ? `${documents.length} доступних документів` : "Доступних документів немає.");
  if (!documents.length) return;
  const list = node("ul", "", "route-list");
  for (const item of documents) {
    const row = node("li", "", "route-card");
    row.append(node("strong", String(item.canonical_title ?? "Без назви")));
    row.append(node("span", `${item.issuer ?? "—"} · ${item.corpus_id ?? "—"} · tier ${item.access_tier ?? "—"}`));
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
  renderState(view, "Джерела цієї сесії", sources.length ? "success" : "empty", sources.length ? `${sources.length} цитованих джерел` : "Ще немає цитованих джерел. Джерело з’являється тут лише після evidence-bound відповіді.");
  if (!sources.length) return;
  const list = node("ul", "", "route-list");
  for (const source of sources) {
    const row = node("li", "", "route-card");
    row.append(node("strong", `${source.title} · ред. ${source.revision}`));
    row.append(node("span", `span ${String(source.span_id).slice(0, 12)}… · sha ${String(source.source_hash).slice(0, 12)}…`));
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
  renderState(view, "Профіль", "success", "Серверно підтверджена ідентичність та runtime policy");
  const list = node("dl", "", "route-metrics");
  const values = [
    ["Subject", identity.subject],
    ["Clearance", identity.clearance],
    ["Roles", (identity.roles ?? []).join(", ") || "—"],
    ["Corpora", (identity.corpora ?? []).join(", ") || "—"],
    ["Permissions", (bootstrap?.effective_permissions ?? []).join(", ") || "—"],
    ["Release", bootstrap?.release],
    ["API", bootstrap?.api_version],
    ["Ingestion", capabilities.ingestion_mode],
    ["Offline", capabilities.offline_pack_enabled ? "enabled" : "disabled"],
    ["Subscription", capabilities.subscription_required ? "required" : "not required"],
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
  renderState(view, "Аудит запиту", "empty", "Введіть X-Request-ID / trace ID. Читання аудиту вимагає серверного audit:read.");
  const form = node("form", "", "route-form");
  const label = node("label", "Trace ID");
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
  renderState(view, "Аудит запиту", events.length ? "success" : "empty", events.length ? `${events.length} подій · trace ${trace}` : `Подій для trace ${trace} не знайдено.`);
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
          renderState(view, "Вхід", "empty", isAuthenticated?.() ? "Сесію вже підтверджено сервером." : "Продовжте через серверний OIDC/session login. Локальна роль не надає доступ.");
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
            renderState(view, "Аудит запиту", "loading", "Читання server-side audit chain…");
            try {
              const events = await call(`/v1/audit/events?trace_id=${encodeURIComponent(trace)}&limit=100`);
              renderAuditEvents(view, trace, Array.isArray(events) ? events : []);
            } catch (error) {
              renderState(view, "Аудит запиту", "error", error instanceof ApiRefusal ? error.reason : "Аудит недоступний");
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
      const reason = error instanceof NetworkError
        ? (error.offline ? "Немає мережі; серверний маршрут не підміняється кешованою відповіддю." : "Мережевий запит не завершено.")
        : error instanceof ApiRefusal ? error.reason : "Маршрут не вдалося завантажити.";
      renderState(view, route?.id ?? "Маршрут", "error", reason);
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
    void navigate(link.getAttribute("href") ?? "/access-denied");
  });
  window.addEventListener("popstate", () => { void render(); });

  return Object.freeze({render, navigate, get current() { return current; }});
}
