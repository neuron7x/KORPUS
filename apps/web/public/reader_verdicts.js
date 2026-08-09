export const VERDICT = Object.freeze({
  answered: ["ПІДСТАВА Є", "ok"],
  insufficient_evidence: ["ПІДСТАВИ НЕМАЄ", "withheld"],
  access_denied: ["ДОСТУП НЕ НАДАНО", "denied"],
  requires_human_review: ["ПОТРІБНА ЛЮДИНА", "withheld"],
});

export const UNFINISHED = new Set([
  "retrieval_deadline_exceeded",
  "retrieval_dependency_unavailable",
]);
