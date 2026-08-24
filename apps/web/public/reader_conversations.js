// Conversation presentation/controller. History is context, never evidence.

import {ApiRefusal, escapeHtml} from "./api.js";
import {
  archiveConversation,
  conversationListMarkup,
  createConversation,
  listConversations,
  readConversation,
  tenancyAvailable,
  titleFrom,
} from "./conversations.js";
import {VERDICT} from "./reader_verdicts.js";

const CONVERSATION_PAGE = 50;

export function createConversationController({publicMode, result, query}) {
  const conversations = document.getElementById("conversations");
  const body = document.getElementById("conversations-body");
  const summary = document.getElementById("conversations-summary");
  let enabled = false;
  let activeConversation = null;
  let shown = CONVERSATION_PAGE;

  async function start() {
    if (publicMode || !conversations) return;
    try {
      enabled = await tenancyAvailable();
    } catch {
      enabled = false;
    }
    if (!enabled) return;
    conversations.hidden = false;
    await refresh();
  }

  async function refresh() {
    if (!enabled) return;
    try {
      const page = await listConversations({limit: shown});
      body.innerHTML = conversationListMarkup(page.items, {
        activeId: activeConversation,
        hasMore: page.has_more,
      });
      summary.textContent = page.items.length
        ? `Розмови · ${page.items.length}${page.has_more ? "+" : ""}`
        : "Розмови";
    } catch (error) {
      body.innerHTML = `<p class="note">Перелік недоступний: ${escapeHtml(
        error instanceof ApiRefusal ? error.reason : "невідома помилка")}</p>`;
    }
  }

  async function forQuestion(question) {
    if (!enabled) return null;
    if (activeConversation) return activeConversation;
    try {
      const created = await createConversation(titleFrom(question));
      activeConversation = created.id;
      return activeConversation;
    } catch {
      // Conversation persistence is convenience; evidence answering can remain stateless.
      return null;
    }
  }

  function renderStoredMessage(message) {
    const block = document.createElement("article");
    block.className = "turn stored";
    if (message.role === "user") {
      block.innerHTML =
        `<p class="turn-question"><span class="turn-mark" aria-hidden="true"></span>${
          escapeHtml(message.text)}</p>`;
      return block;
    }
    const [verdict, tone] = message.answer_status
      ? VERDICT[message.answer_status] ?? ["ВІДМОВА", "withheld"]
      : ["ВЕРДИКТ НЕ ЗАПИСАНО", "withheld"];
    block.innerHTML =
      `<div class="verdict ${tone}"><span class="verdict-mark" aria-hidden="true"></span>` +
      `<h2>${escapeHtml(verdict)}</h2></div>` +
      `<p class="answer-text">${escapeHtml(message.text).replaceAll("\n", "<br>")}</p>` +
      `<p class="note">З історії. Текст відповіді збережено дослівно; картки цитат із
       хешами належать тому запиту й лишаються в журналі аудиту.</p>`;
    return block;
  }

  async function open(id) {
    try {
      const page = await readConversation(id);
      activeConversation = id;
      result.innerHTML = "";
      result.classList.remove("hidden", "error");
      if (!page.items.length) {
        const empty = document.createElement("p");
        empty.className = "note";
        empty.textContent = "Розмова порожня.";
        result.append(empty);
      }
      if (page.has_more) {
        const cut = document.createElement("p");
        cut.className = "note truncated";
        cut.textContent =
          `Показано перші ${page.items.length} ходів цієї розмови. Пізніші не показані.`;
        result.append(cut);
      }
      for (const message of page.items) result.append(renderStoredMessage(message));
      await refresh();
      query.focus();
    } catch (error) {
      body.innerHTML = `<p class="note">Не відкрито: ${escapeHtml(
        error instanceof ApiRefusal ? error.reason : "невідома помилка")}</p>`;
    }
  }

  body?.addEventListener("click", event => {
    const openButton = event.target.closest("[data-conversation]");
    if (openButton) {
      void open(openButton.dataset.conversation);
      return;
    }
    if (event.target.closest('[data-more="conversations"]')) {
      shown = Math.min(shown + CONVERSATION_PAGE, 200);
      void refresh();
      return;
    }
    const archive = event.target.closest("[data-archive]");
    if (!archive) return;
    const id = archive.dataset.archive;
    archiveConversation(id)
      .then(() => {
        if (activeConversation === id) activeConversation = null;
        return refresh();
      })
      .catch(error => {
        body.innerHTML = `<p class="note">Не архівовано: ${escapeHtml(
          error instanceof ApiRefusal ? error.reason : "невідома помилка")}</p>`;
      });
  });

  document.getElementById("conversation-new")?.addEventListener("click", () => {
    activeConversation = null;
    result.innerHTML = "";
    result.classList.add("hidden");
    void refresh();
    query.focus();
  });

  return {
    start,
    refresh,
    forQuestion,
  };
}
