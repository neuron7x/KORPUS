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
  } else if (detail && typeof detail === "object") {
    // A typed refusal: `{reason, detail}`. This branch did not exist, so every one of
    // them rendered as "API 409" — found in a browser, on the one refusal where the
    // sentence is the whole point: "you cannot disable your own account; ask another
    // administrator". The reader surface had worked around it locally; the console had
    // not, and a second workaround would have been the wrong fix twice.
    reason = String(detail.detail ?? detail.reason ?? reason);
  }
  return new ApiRefusal(response.status, reason, payload);
}

// A dropped network is the field's normal state, not an exotic one. Without a deadline a
// request against a broken uplink hangs on an open TCP socket for the OS default — over a
// minute — with the button disabled the whole time, and the soldier cannot tell "no signal"
// from "the system is broken". `NetworkError.offline` is true when the failure is the link
// rather than the server, so the caller can say so in words and keep the question.
export class NetworkError extends Error {
  constructor(offline) {
    super(offline ? "network offline" : "network request failed");
    this.name = "NetworkError";
    this.offline = offline;
  }
}

//: A field radio, not a datacentre link. Long enough for a slow uplink to answer, short
//: enough that a dead one returns the button before the soldier gives up on the page.
const REQUEST_TIMEOUT_MS = 30000;

export async function call(path, {method = "GET", body, form} = {}) {
  const headers = form ? authHeaders({}, method) : authHeaders(
    body === undefined ? {} : {"Content-Type": "application/json"},
    method,
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
    // fetch rejects only for transport failures — the link, DNS, a timeout, an abort.
    // An HTTP error status resolves and is handled below. `navigator.onLine === false` is
    // a definite "no link"; a timeout or bare TypeError with the browser still online is
    // treated as offline too, because from the field the distinction is not actionable.
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
