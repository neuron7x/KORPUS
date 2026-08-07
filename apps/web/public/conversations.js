// The transcript that outlives the tab, and the rule that keeps it from becoming evidence.
//
// Until now every answer lived in one `<section>` and died with the tab. A soldier who
// asked three questions under fire, closed the browser and came back had nothing — not the
// answers, not the citations, not what they had already ruled out. ACT-001 gave the API
// conversations; this is the surface for them.
//
// Two rules the interface has to keep saying out loud, because the API cannot say them for
// it:
//
//   history is context, never a source
//       a stored assistant turn is rendered with its citations *as they were recorded* and
//       is never sent back as part of a question. `askIn` posts the question alone. An
//       interface that quietly prepended the transcript would make the system cite itself
//       within three turns, with a citation list that looks complete.
//
//   the transcript is one account's
//       every call carries the conversation id and nothing else; the server scopes by the
//       authenticated account. There is no account selector here, because a client that
//       could name an account is a client choosing whose history to read.
//
// Off on the public edge. There the edge attaches one read-only identity to every visitor,
// so a conversation would be a shared notebook: everybody writing into one account's
// history and reading each other's questions.

import { ApiRefusal, call, escapeHtml } from "./api.js";

/** Whether this deployment serves the account surface at all. */
export async function tenancyAvailable() {
  try {
    await call("/v1/account");
    return true;
  } catch (error) {
    // 401/403 is an answer about *this reader*, not about the deployment: an expired
    // token or a disabled account. Anything else — 404 on a build without the routes,
    // 503 when the services are not wired — means there is no account surface here, and
    // the page falls back to the stateless `/v1/answers` path it has always had.
    if (error instanceof ApiRefusal && [401, 403].includes(error.status)) throw error;
    return false;
  }
}

export function listConversations() {
  return call("/v1/conversations");
}

export function createConversation(title) {
  return call("/v1/conversations", {method: "POST", body: {title: title ?? null}});
}

export function readConversation(id) {
  return call(`/v1/conversations/${encodeURIComponent(id)}`);
}

export function archiveConversation(id) {
  return call(`/v1/conversations/${encodeURIComponent(id)}/archive`, {method: "POST"});
}

/** One question, inside one conversation. The transcript is not sent with it. */
export function askIn(id, body) {
  return call(`/v1/conversations/${encodeURIComponent(id)}/ask`, {method: "POST", body});
}

/** A title a reader recognises in a list, from the first thing they asked. */
export function titleFrom(question) {
  const cleaned = String(question ?? "").replace(/\s+/g, " ").trim();
  if (!cleaned) return null;
  return cleaned.length > 60 ? `${cleaned.slice(0, 57)}…` : cleaned;
}

const RELATIVE = [
  [60, "щойно", () => "щойно"],
  [3600, "хв", value => `${Math.floor(value / 60)} хв тому`],
  [86400, "год", value => `${Math.floor(value / 3600)} год тому`],
];

/**
 * How long ago, in words. `now` is a parameter so the function is testable without
 * mocking a clock — a formatter that reads the wall clock can only be tested by moving it.
 */
export function relativeTime(iso, now = Date.now()) {
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return "";
  const seconds = Math.max(0, (now - parsed) / 1000);
  for (const [bound, , render] of RELATIVE) {
    if (seconds < bound) return render(seconds);
  }
  const days = Math.floor(seconds / 86400);
  return days === 1 ? "учора" : `${days} дн тому`;
}

/**
 * The list, as markup. Separated from the DOM so the ordering and the labels can be
 * tested without a browser: what a reader recognises a conversation by is its own
 * question and when it was last touched, and both are easy to lose in a refactor.
 */
export function conversationListMarkup(items, {activeId = null, now = Date.now()} = {}) {
  if (!items.length) {
    return `<p class="note">Розмов ще немає. Перше питання почне нову.</p>`;
  }
  return `<ul class="conversation-list">${
    items.map(item => {
      const current = item.id === activeId;
      return `<li${current ? ' class="current"' : ""}>` +
        `<button type="button" class="conversation-open" data-conversation="${
          escapeHtml(item.id)}"${current ? ' aria-current="true"' : ""}>` +
        `<span class="conversation-title">${
          escapeHtml(item.title || "Без назви")}</span>` +
        `<span class="conversation-when">${escapeHtml(relativeTime(item.updated_at, now))}</span>` +
        `</button>` +
        `<button type="button" class="conversation-archive secondary" data-archive="${
          escapeHtml(item.id)}" aria-label="Архівувати: ${
          escapeHtml(item.title || "без назви")}">Архів</button>` +
        `</li>`;
    }).join("")
  }</ul>`;
}
