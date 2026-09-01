// Canonical deep-link registry. Authentication is necessary but not sufficient:
// permission/capability projection comes from /v1/client/bootstrap and is fail-closed.

const STATIC = Object.freeze([
  ["login", "/login", false, null, null],
  ["chat", "/chat", true, "answer:read", null],
  ["knowledge", "/knowledge", true, "document:list", null],
  ["documents", "/documents", true, "document:list", null],
  ["sources", "/sources", true, "answer:read", null],
  ["offline", "/offline", true, "answer:read", "offline_pack_enabled"],
  ["audit", "/audit", true, "audit:read", null],
  ["profile", "/profile", true, null, null],
  ["access-denied", "/access-denied", false, null, null],
]);

export const ROUTES = Object.freeze(STATIC.map(([id, path, auth, permission, capability]) =>
  Object.freeze({id, path, auth, permission, capability})));
const BY_PATH = new Map(ROUTES.map(route => [route.path, route]));

function safeSegment(value) {
  if (typeof value !== "string" || value.length === 0 || value.length > 128) return null;
  if (!/^[A-Za-z0-9._~-]+$/.test(value)) return null;
  return value;
}

export function resolveRoute(pathname) {
  if (typeof pathname !== "string") return null;
  let path;
  try { path = decodeURI(pathname.split("?", 1)[0] || "/"); } catch { return null; }
  if (path.length > 512 || /[\0\r\n]/.test(path)) return null;
  if (path !== "/" && path.endsWith("/")) path = path.slice(0, -1);
  if (path === "/") return BY_PATH.get("/chat");
  const direct = BY_PATH.get(path);
  if (direct) return direct;
  const match = path.match(/^\/chat\/([^/]+)$/);
  if (match) {
    const conversationId = safeSegment(match[1]);
    return conversationId
      ? Object.freeze({id: "chat-conversation", path, auth: true, permission: "answer:read", capability: null, params: Object.freeze({conversationId})})
      : null;
  }
  return null;
}

export function routeHref(id, params = {}) {
  if (id === "chat-conversation") {
    const value = safeSegment(params.conversationId);
    if (!value) throw new Error("invalid conversation id");
    return `/chat/${encodeURIComponent(value)}`;
  }
  const route = ROUTES.find(item => item.id === id);
  if (!route) throw new Error(`unknown route: ${id}`);
  return route.path;
}

export function routeAccess(route, authenticated, bootstrap = null) {
  if (!route) return Object.freeze({allowed: false, redirect: "/access-denied"});
  if (route.auth && !authenticated) return Object.freeze({allowed: false, redirect: "/login"});
  if (!route.auth) return Object.freeze({allowed: true, redirect: null});
  const permissions = new Set(bootstrap?.effective_permissions ?? []);
  if (route.permission && !permissions.has(route.permission)) {
    return Object.freeze({allowed: false, redirect: "/access-denied"});
  }
  if (route.capability && bootstrap?.capabilities?.[route.capability] !== true) {
    return Object.freeze({allowed: false, redirect: "/access-denied"});
  }
  return Object.freeze({allowed: true, redirect: null});
}

export function routeState(kind, value = null) {
  if (!["loading", "empty", "success", "error"].includes(kind)) throw new Error(`invalid route state: ${kind}`);
  if (kind === "error" && !(value instanceof Error) && typeof value !== "string") {
    throw new Error("error state requires a reason");
  }
  return Object.freeze({kind, value});
}
