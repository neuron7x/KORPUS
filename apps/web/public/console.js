// Operator consoles: ingestion, review, rescission, corpus, audit.
//
// WEB-001 recorded that the interface covered question-and-answer and nothing else, so
// ingestion, quarantine, review, approval and audit inspection were done by hand
// against the API or the database. The acceptance predicate is that every critical
// workflow is executable without raw DB/API manipulation.
//
// Three properties make that safe rather than merely possible:
//
//   1. Nothing irreversible fires without a preview. `preview` renders the exact
//      payload and the audit consequence; `submit` stays disabled until it has been
//      shown, and any subsequent edit disables it again. A form that submits on the
//      first click is how an approval lands on the wrong version id.
//   2. Validation comes from the generated contract, not from hand-copied rules. See
//      scripts/generate_web_contract.py for why.
//   3. A refusal is rendered verbatim with its status. "Something went wrong" is what
//      sends an operator back to psql, which is the behaviour this console exists to
//      remove.
//
// Which consoles appear follows the permissions the *server* reported for the identity.
// That is presentation. Authorization is the server's, every time.
//
// Every rule above lives in console_rules.js and is tested there. This file is the
// wiring: read the form, call the rule, render the outcome.

import {
  ApiRefusal, call, clearBearerToken, escapeHtml, loginUrl, setBearerToken,
} from "./api.js";
import {CONTRACT} from "./contract.js";
import {wireAccounts} from "./console_accounts.js";
import {wireMutationForms} from "./console_mutations.js";
import {wireReadOnly} from "./console_readonly.js";
import {previewMatches, visibleConsoles} from "./console_rules.js";

const $ = id => document.getElementById(id);
const identityState = $("identity-state");

// ---------------------------------------------------------------- rendering

// Every outcome panel starts with a sentence rather than an empty box. An empty panel
// beside a form reads as "nothing happened yet" and as "it ran and produced nothing",
// and those are different states.
const IDLE = {
  "ingest-result": "Тут з’явиться попередній перегляд і результат внесення.",
  "job-result": "Стан завдання показується тут.",
  "review-result": "Тут з’явиться попередній перегляд рішення та відповідь сервера.",
  "rescind-result": "Тут з’явиться попередній перегляд скасування чинності.",
  "documents-result": "Натисніть «Оновити перелік».",
  "spans-result": "Фрагменти вибраної версії показуються тут.",
  "audit-verify-result": "Натисніть «Перевірити ланцюг».",
  "audit-events-result": "Події вказаного трасування показуються тут.",
};

function idle(target) {
  target.classList.remove("error");
  target.innerHTML = `<p class="idle">${escapeHtml(IDLE[target.id] ?? "")}</p>`;
}

function busy(target, message) {
  target.classList.remove("error");
  target.innerHTML = `<p class="idle">${escapeHtml(message)}</p>`;
}

function renderRefusal(target, error) {
  if (error instanceof ApiRefusal) {
    target.innerHTML =
      `<p class="refusal">Відмова ${escapeHtml(error.status)}</p>` +
      `<p class="reason">${escapeHtml(error.reason)}</p>`;
  } else {
    target.innerHTML = `<p class="refusal">${escapeHtml(error?.message ?? "невідома помилка")}</p>`;
  }
  target.classList.add("error");
}

function renderJson(target, heading, payload) {
  target.classList.remove("error");
  target.innerHTML =
    `<h4>${escapeHtml(heading)}</h4>` +
    `<pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>`;
}

function renderPreview(target, payload, consequence) {
  target.classList.remove("error");
  target.innerHTML =
    `<h4>Буде надіслано</h4><pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>` +
    `<h4>Наслідок</h4><p class="consequence">${escapeHtml(consequence)}</p>`;
}

function renderProblems(target, problems) {
  target.classList.add("error");
  target.innerHTML =
    `<h4>Запит не надіслано</h4><ul>${
      problems.map(problem => `<li>${escapeHtml(problem)}</li>`).join("")
    }</ul>`;
}

// ---------------------------------------------------------------- enums

function option(value, label) {
  const element = document.createElement("option");
  element.value = String(value);
  element.textContent = label ?? String(value);
  return element;
}

const TIER_LABELS = {0: "0 · public", 1: "1 · authenticated", 2: "2 · reviewed", 3: "3 · restricted"};

function fillEnums() {
  for (const value of CONTRACT.enums.Classification) $("doc-classification").append(option(value));
  for (const value of CONTRACT.enums.AccessTier) $("doc-tier").append(option(value, TIER_LABELS[value]));
  for (const value of CONTRACT.enums.AuthorityClass) $("ver-authority").append(option(value));
  // Only the states a reviewer decides. `quarantined` is where ingestion puts a version,
  // not somewhere a reviewer sends one, and offering it as a target invites an operator
  // to try a transition the server will refuse.
  for (const value of CONTRACT.enums.ReviewState) {
    if (value !== "quarantined") $("review-target").append(option(value));
  }
  $("review-tier").append(option("", "не змінювати"));
  for (const value of CONTRACT.enums.AccessTier) $("review-tier").append(option(value, TIER_LABELS[value]));
}

// ------------------------------------------------- preview / submit gating

function gate(form, previewButton, submitButton, outcome, build, consequence, send) {
  let confirmed = null;

  const invalidate = () => {
    confirmed = null;
    submitButton.disabled = true;
  };
  form.addEventListener("input", invalidate);
  form.addEventListener("change", invalidate);

  previewButton.addEventListener("click", () => {
    const payload = build();
    if (payload.problems.length) {
      renderProblems(outcome, payload.problems);
      invalidate();
      return;
    }
    confirmed = JSON.stringify(payload.body);
    submitButton.disabled = false;
    renderPreview(outcome, payload.body, consequence(payload.body));
  });

  form.addEventListener("submit", async event => {
    event.preventDefault();
    const payload = build();
    if (payload.problems.length) {
      renderProblems(outcome, payload.problems);
      invalidate();
      return;
    }
    if (!previewMatches(confirmed, payload.body)) {
      // Reachable when the form changes without firing input/change — a file chosen
      // through a drop, an autofill. The submit path re-compares rather than trusting
      // that the earlier confirmation still describes what is about to be sent.
      renderProblems(outcome, ["форма змінилася після попереднього перегляду; перегляньте ще раз"]);
      invalidate();
      return;
    }
    submitButton.disabled = true;
    busy(outcome, "Надсилаю…");
    try {
      renderJson(outcome, "Виконано", await send(payload));
    } catch (error) {
      renderRefusal(outcome, error);
    } finally {
      invalidate();
    }
  });
}

// ---------------------------------------------------------------- tabs

//: Every console, in the order the tabs appear. A console missing from here is rendered
//: nowhere and hidden nowhere: it stays visible on every tab switch, which is how the
//: accounts panel would have leaked onto a curator's screen.
const TABS = [
  "console-curator", "console-reviewer", "console-corpus", "console-auditor",
  "console-accounts",
];

function selectTab(id) {
  for (const name of TABS) {
    const tab = $(`tab-${name}`);
    const panel = $(name);
    const selected = name === id;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    panel.hidden = !selected;
  }
}

function wireTabs() {
  for (const [index, name] of TABS.entries()) {
    const tab = $(`tab-${name}`);
    tab.addEventListener("click", () => selectTab(name));
    // Arrow keys are how a screen-reader user moves between tabs; without them the
    // tablist role is a promise the page does not keep.
    tab.addEventListener("keydown", event => {
      const step = {ArrowRight: 1, ArrowLeft: -1}[event.key];
      if (step === undefined) return;
      const shown = TABS.filter(candidate => !$(`tab-${candidate}`).hidden);
      if (shown.length < 2) return;
      const position = shown.indexOf(TABS[index]);
      const next = shown[(position + step + shown.length) % shown.length];
      event.preventDefault();
      selectTab(next);
      $(`tab-${next}`).focus();
    });
  }
}

// ---------------------------------------------------------------- identity

//: Who the server said this is, kept for the one consequence line that needs it: telling
//: an operator that the account they selected is their own, before the server refuses it.
//: Held here rather than read from a form — the subject is the server's answer, not a
//: field somebody can type into.
let signedIn = null;

function applyIdentity(currentIdentity) {
  signedIn = currentIdentity;
  const visible = new Set(currentIdentity ? visibleConsoles(currentIdentity) : []);
  for (const name of TABS) {
    $(`tab-${name}`).hidden = !visible.has(name);
    $(name).hidden = true;
  }
  $("console-none").hidden = !(currentIdentity && visible.size === 0);
  const first = TABS.find(name => visible.has(name));
  if (first) selectTab(first);
}

async function loadIdentity() {
  identityState.textContent = "Перевірка…";
  const loaded = await call("/v1/auth/me");
  identityState.innerHTML =
    `<strong>${escapeHtml(loaded.subject)}</strong> · clearance ${escapeHtml(loaded.clearance)} · ` +
    `${escapeHtml([...loaded.roles].sort().join(", "))}`;
  $("login").hidden = true;
  $("logout").hidden = false;
  applyIdentity(loaded);
  return loaded;
}

function forgetIdentity(message) {
  clearBearerToken();
  applyIdentity(null);
  $("login").hidden = false;
  $("logout").hidden = true;
  identityState.textContent = message;
}

// ---------------------------------------------------------------- wiring

fillEnums();
wireTabs();
for (const id of Object.keys(IDLE)) idle($(id));

// One listener rather than one per identifier: the tables are rewritten on every
// refresh, so per-element handlers would have to be re-attached each time.
document.addEventListener("click", async event => {
  const trigger = event.target.closest?.(".copyable");
  if (!trigger) return;
  try {
    await navigator.clipboard.writeText(trigger.dataset.copy);
    const original = trigger.textContent;
    trigger.textContent = "скопійовано";
    setTimeout(() => { trigger.textContent = original; }, 900);
  } catch {
    // Clipboard access can be refused; the identifier is still selectable by hand.
  }
});

$("check-auth").addEventListener("click", async () => {
  setBearerToken($("bearer-token").value);
  try {
    await loadIdentity();
    $("bearer-token").value = "";
  } catch (error) {
    forgetIdentity(`Відмова: ${error instanceof ApiRefusal ? error.reason : "невідома помилка"}`);
  }
});

$("login").addEventListener("click", () => {
  window.location.assign(loginUrl(window.location.pathname));
});

$("logout").addEventListener("click", async () => {
  try {
    await call("/v1/auth/logout", {method: "POST"});
    forgetIdentity("Не автентифіковано.");
  } catch (error) {
    identityState.textContent =
      `Logout відхилено: ${error instanceof ApiRefusal ? error.reason : "невідома помилка"}`;
  }
});

wireMutationForms(gate);
wireReadOnly({busy, renderProblems, renderRefusal});
wireAccounts({
  gate, renderJson, renderProblems, renderRefusal, busy,
  getSignedIn: () => signedIn,
});

loadIdentity().catch(() => forgetIdentity("Не автентифіковано."));
