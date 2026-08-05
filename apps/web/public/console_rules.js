// The decisions the consoles make, with no DOM under them.
//
// Split out of console.js so they can be executed by `node --test`. console.js runs its
// wiring at import time and needs a document; anything left inside it is reachable only
// by a browser, and a check that needs a browser is a check the pipeline does not run.
// What stayed there is event handling and rendering. What moved here is every rule that
// can be wrong: which console a role sees, which submissions are refused before they
// leave, and what an operator is told an action will do.

import {CONTRACT} from "./contract.js";

// Generated from ROLE_PERMISSIONS in apps/api/src/korpus/application/policy.py. Used to
// decide which console to *show*, never whether an action is allowed: the server
// refuses regardless, and a UI that hides a button has not implemented access control.
export function permissionsOf(identity) {
  const granted = new Set();
  for (const role of identity?.roles ?? []) {
    for (const permission of CONTRACT.roles[role] ?? []) granted.add(permission);
  }
  return granted;
}

export function permits(identity, permission) {
  const granted = permissionsOf(identity);
  return granted.has("*") || granted.has(permission);
}

export function visibleConsoles(identity) {
  const visible = [];
  if (permits(identity, "document:ingest")) visible.push("console-curator");
  if (permits(identity, "document:review") || permits(identity, "document:approve")) {
    visible.push("console-reviewer");
  }
  if (permits(identity, "document:list")) visible.push("console-corpus");
  if (permits(identity, "audit:verify") || permits(identity, "audit:read")) {
    visible.push("console-auditor");
  }
  return visible;
}

// Checks only what the JSON Schema states. Model validators — that access_tier must
// reach the classification minimum, that effective_until cannot precede effective_from
// — are not in the schema, are not reimplemented here, and come back from the server as
// a 422 rendered verbatim. Guessing at them in the browser is how the client starts
// refusing what the API accepts, and that failure is invisible: nobody reports a form
// that would not submit something they never tried to submit.
export function validateAgainst(model, payload) {
  const fields = CONTRACT.models[model];
  if (!fields) throw new Error(`no generated constraints for ${model}`);
  const problems = [];
  for (const field of fields) {
    const value = payload[field.name];
    const absent = value === undefined || value === null || value === "";
    if (field.required && absent) {
      problems.push(`${field.name}: обов'язкове поле`);
      continue;
    }
    if (absent) continue;
    if (field.enum) {
      if (!CONTRACT.enums[field.enum].includes(value)) {
        problems.push(`${field.name}: значення поза переліком ${field.enum}`);
      }
      continue;
    }
    if (typeof value !== "string") continue;
    if (field.minLength !== undefined && value.length < field.minLength) {
      problems.push(`${field.name}: щонайменше ${field.minLength} символів, зараз ${value.length}`);
    }
    if (field.maxLength !== undefined && value.length > field.maxLength) {
      problems.push(`${field.name}: щонайбільше ${field.maxLength} символів, зараз ${value.length}`);
    }
    if (field.pattern !== undefined && !new RegExp(field.pattern).test(value)) {
      problems.push(`${field.name}: не відповідає ${field.pattern}`);
    }
  }
  return problems;
}

// A preview is bound to the payload it previewed. Comparing the serialised body — not
// remembering that a preview happened — is what makes an edit between confirmation and
// submission fall back to a refusal instead of shipping something nobody saw.
export function previewMatches(confirmed, body) {
  return confirmed !== null && confirmed === JSON.stringify(body);
}

export function reviewProblems(body, versionId) {
  const problems = validateAgainst("ReviewTransition", body);
  if (!versionId) problems.push("ідентифікатор версії: обов'язковий");
  // The schema cannot express it and the server refuses it, but the operator would
  // learn that only after submitting a decision — so the form says it first.
  if (body.access_tier !== undefined && body.target !== "approved") {
    problems.push("рівень доступу задається лише при затвердженні");
  }
  return problems;
}

export function rescissionProblems(body, versionId) {
  const problems = validateAgainst("RescissionRequest", body);
  if (!versionId) problems.push("ідентифікатор версії: обов'язковий");
  return problems;
}

export function ingestProblems(document_, version, hasFile) {
  const problems = [
    ...validateAgainst("DocumentCreate", document_),
    ...validateAgainst("VersionCreate", version),
  ];
  if (!hasFile) problems.push("файл джерела: обов'язковий");
  return problems;
}

// ------------------------------------------------------------ consequences
//
// What the operator is told will happen, shown before the action fires. These are the
// sentences that make a preview worth reading: a JSON body says `"target":"approved"`,
// which is not the same as being told the version becomes citable.

export function ingestConsequence(body) {
  return (
    `Версія «${body.version.revision}» документа «${body.document.canonical_title}» ` +
    "потрапляє до карантину. Подія внесення входить до ланцюга аудиту разом із " +
    "sha256 завантаженого файлу. Цитування стане можливим лише після затвердження."
  );
}

const REVIEW_EFFECTS = {
  approved: "версія стає придатною до цитування у відповідях",
  rejected: "версія лишається поза корпусом остаточно",
  metadata_reviewed: "версія просувається до перевірки змісту",
  content_reviewed: "версія стає готовою до затвердження",
};

export function reviewConsequence(body) {
  const effect = REVIEW_EFFECTS[body.target] ?? "стан змінюється";
  const tier = body.access_tier === undefined
    ? ""
    : ` Рівень доступу встановлюється на ${body.access_tier}.`;
  return (
    `${effect}. Рішення, ваш субʼєкт і обґрунтування дослівно входять до ланцюга аудиту ` +
    `і не редагуються.${tier}`
  );
}

export function rescissionConsequence(body) {
  return (
    "Версія лишається затвердженою, але виходить з чинності " +
    (body.rescinded_at ? `від ${body.rescinded_at}` : "негайно") +
    ". Відповіді, що спираються на пізніші дати, більше її не цитуватимуть."
  );
}
