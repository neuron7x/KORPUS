// One place where the browser talks to the API.
//
// WEB-001 adds a second page. Two pages meant two copies of the auth handling, and the
// copy is where a token ends up in localStorage rather than in memory, or a
// state-changing request goes out without the CSRF header because someone wrote `fetch`
// directly. Neither is a bug a reviewer catches by reading — both are omissions.
//
// So every request goes through `call`, the bearer token lives in this module and
// nowhere else, and the CSRF header is attached by method rather than by the caller
// remembering to ask for it.

// Read per call, not at import. config.js is a separate <script> and module evaluation
// order is not something a page should depend on; reading it once at load time also
// makes this module require a `window` to be imported at all, which put the pure
// permission helpers below out of reach of any test that is not a browser.
const apiUrl = () => globalThis.window?.KORPUS_CONFIG?.apiUrl ?? "/api";
let bearerToken = "";

export function setBearerToken(value) {
  bearerToken = String(value ?? "").trim();
}

export function clearBearerToken() {
  bearerToken = "";
}

export function readCookie(name) {
  const prefix = `${encodeURIComponent(name)}=`;
  const item = document.cookie.split("; ").find(value => value.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : "";
}

export function authHeaders(extra = {}, method = "GET") {
  const headers = {...extra};
  if (bearerToken) headers.Authorization = `Bearer ${bearerToken}`;
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = readCookie("__Host-korpus_csrf");
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  return headers;
}

// A refusal is a result, not a failure. The console renders `reason` verbatim: the API
// answers a rejected approval with "approver clearance below target tier", and
// replacing that with "request failed" is how an operator ends up in psql.
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
  try {
    payload = await response.json();
  } catch {
    return new ApiRefusal(response.status, reason, null);
  }
  const detail = payload?.detail;
  if (typeof detail === "string") {
    reason = detail;
  } else if (Array.isArray(detail)) {
    // FastAPI's 422 body is a list of per-field errors. Flattening it to "unprocessable
    // entity" throws away the only part an operator can act on — which field, and why.
    reason = detail
      .map(item => `${(item.loc ?? []).filter(part => part !== "body").join(".")}: ${item.msg}`)
      .join("; ");
  }
  return new ApiRefusal(response.status, reason, payload);
}

export async function call(path, {method = "GET", body, form} = {}) {
  const headers = form ? authHeaders({}, method) : authHeaders(
    body === undefined ? {} : {"Content-Type": "application/json"},
    method,
  );
  const response = await fetch(`${apiUrl()}${path}`, {
    method,
    headers,
    credentials: "same-origin",
    body: form ?? (body === undefined ? undefined : JSON.stringify(body)),
  });
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
