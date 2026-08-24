import {call} from "./api.js";
import {accountConsequence, accountStatusProblems} from "./console_rules.js";

const $ = id => document.getElementById(id);

export function wireAccounts({gate, renderJson, renderProblems, renderRefusal, busy, getSignedIn}) {
  let foundSubject = null;

  $("account-find-form")?.addEventListener("submit", async event => {
    event.preventDefault();
    const target = $("account-find-result");
    const subject = $("account-subject").value.trim();
    if (!subject) return renderProblems(target, ["субʼєкт: обовʼязковий"]);
    busy(target, "Шукаю…");
    try {
      const account = await call(`/v1/admin/accounts/${encodeURIComponent(subject)}`);
      $("account-id").value = account.id;
      foundSubject = account.auth_subject;
      renderJson(target, "Знайдено", account);
    } catch (error) {
      $("account-id").value = "";
      foundSubject = null;
      renderRefusal(target, error);
    }
  });

  function buildAccountStatus() {
    const body = {
      account_id: $("account-id").value.trim(),
      status: $("account-status").value,
      reason: $("account-reason").value.trim(),
    };
    return {body, problems: accountStatusProblems(body).map(problem => problem.message)};
  }

  gate(
    $("account-status-form"), $("account-preview"), $("account-submit"),
    $("account-status-result"), buildAccountStatus,
    body => accountConsequence(body, {
      ownSubject: getSignedIn()?.subject ?? null,
      targetSubject: foundSubject,
    }),
    payload => call(
      `/v1/admin/accounts/${encodeURIComponent(payload.body.account_id)}/status`,
      {method: "POST", body: {status: payload.body.status, reason: payload.body.reason}},
    ),
  );
}
