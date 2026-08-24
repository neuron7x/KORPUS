import {TRANSPORT_CONTRACT} from "./transport_contract.js";

const apiUrl = () => globalThis.window?.KORPUS_CONFIG?.apiUrl ?? "/api";
let bearerToken = "";

export function setBearerToken(value) { bearerToken = String(value ?? "").trim(); }
export function clearBearerToken() { bearerToken = ""; }

export function readCookie(name) {
  const prefix = `${encodeURIComponent(name)}=`;
  const item = document.cookie.split("; ").find(value => value.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : "";
}

export function authHeaders(extra = {}, method = "GET") {
  const headers = {...extra, "X-KORPUS-Client-Version": TRANSPORT_CONTRACT.release};
  if (bearerToken) headers.Authorization = `Bearer ${bearerToken}`;
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = readCookie("__Host-korpus_csrf");
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  return headers;
}

export class ApiRefusal extends Error {
  constructor(status, reason, payload) {
    super(reason);
    this.name = "ApiRefusal";
    this.status = status;
    this.reason = reason;
    this.payload = payload;
  }
}

async function refusalFrom(response) {
  let payload = null;
  let reason = `API ${response.status}`;
  try { payload = await response.json(); } catch { return new ApiRefusal(response.status, reason, null); }
  const detail = payload?.detail;
  if (typeof detail === "string") reason = detail;
  else if (Array.isArray(detail)) {
    reason = detail.map(item => `${(item.loc ?? []).filter(part => part !== "body").join(".")}: ${item.msg}`).join("; ");
  } else if (detail && typeof detail === "object") {
    reason = String(detail.detail ?? detail.reason ?? reason);
  }
  return new ApiRefusal(response.status, reason, payload);
}

export class NetworkError extends Error {
  constructor(offline) {
    super(offline ? "network offline" : "network request failed");
    this.name = "NetworkError";
    this.offline = offline;
  }
}

const REQUEST_TIMEOUT_MS = 30000;

function transportPath(path) {
  if (typeof path !== "string" || !path.startsWith("/")) throw new Error("API path must be absolute");
  return path.split("?", 1)[0];
}

function templateMatches(template, path) {
  const expected = template.split("/").filter(Boolean);
  const observed = path.split("/").filter(Boolean);
  return expected.length === observed.length && expected.every(
    (part, index) => (part.startsWith("{") && part.endsWith("}")) || part === observed[index],
  );
}

export function assertTransportRoute(path, method = "GET") {
  const clean = transportPath(path);
  const verb = String(method).toUpperCase();
  for (const table of [TRANSPORT_CONTRACT.paths, TRANSPORT_CONTRACT.hidden_browser_routes]) {
    for (const [template, methods] of Object.entries(table ?? {})) {
      if (methods.includes(verb) && templateMatches(template, clean)) return true;
    }
  }
  throw new Error(`transport contract refuses ${verb} ${clean}`);
}

export async function call(path, {method = "GET", body, form} = {}) {
  assertTransportRoute(path, method);
  const headers = form ? authHeaders({}, method) : authHeaders(
    body === undefined ? {} : {"Content-Type": "application/json"}, method,
  );
  let response;
  try {
    response = await fetch(`${apiUrl()}${path}`, {
      method,
      headers,
      credentials: "same-origin",
      body: form ?? (body === undefined ? undefined : JSON.stringify(body)),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    const offline = globalThis.navigator?.onLine === false
      || error?.name === "TimeoutError"
      || error?.name === "AbortError"
      || error instanceof TypeError;
    throw new NetworkError(offline);
  }
  if (!response.ok) throw await refusalFrom(response);
  if (response.status === 204) return null;
  return response.json();
}

export function loginUrl(returnTo) {
  return `${apiUrl()}/v1/auth/login?return_to=${encodeURIComponent(returnTo)}`;
}

export function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[char]);
}
