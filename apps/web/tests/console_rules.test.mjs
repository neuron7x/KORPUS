// WEB-001: the console's rules, executed rather than read.
//
// The finding asks for "E2E role tests". A browser-driving suite is not something this
// pipeline can run, and a check that does not run is not a control — so what runs here
// is every decision the console makes with the DOM taken out from under it: which
// console a role is shown, what is refused before it leaves the browser, and what the
// operator is told an action will do. Driving a real browser through a real login stays
// external, and is recorded as such in TECHNICAL_DEBT_V5.md.

import test from "node:test";
import assert from "node:assert/strict";

import {CONTRACT} from "../public/contract.js";
import {
  ingestConsequence, ingestProblems, permissionsOf, permits, previewMatches,
  rescissionConsequence, rescissionProblems, reviewConsequence, reviewProblems,
  validateAgainst, visibleConsoles,
} from "../public/console_rules.js";

const identity = (...roles) => ({subject: "s", roles, clearance: 3});

const validDocument = {
  canonical_title: "Настанова з ведення журналу",
  corpus_id: "public",
  issuer: "Генеральний штаб",
  jurisdiction: "UA",
  document_type: "reference",
  access_tier: 0,
  classification: "public",
  compartments: [],
};
const validVersion = {revision: "1.0", authority: "official_ua"};

// ------------------------------------------------------------ role visibility

test("a curator sees ingestion and the corpus, not review or audit", () => {
  assert.deepEqual(visibleConsoles(identity("curator")), ["console-curator", "console-corpus"]);
});

test("a reviewer sees review and the corpus, not ingestion", () => {
  assert.deepEqual(visibleConsoles(identity("reviewer")), ["console-reviewer", "console-corpus"]);
});

test("an auditor sees audit and the corpus, and cannot write anything", () => {
  assert.deepEqual(visibleConsoles(identity("auditor")), ["console-corpus", "console-auditor"]);
});

test("an ordinary user sees only the corpus", () => {
  assert.deepEqual(visibleConsoles(identity("user")), ["console-corpus"]);
});

test("an admin sees every console through the wildcard", () => {
  // Enumerated rather than counted, so a console added later fails here and somebody has
  // to decide who sees it — which is how the accounts console arrived.
  assert.deepEqual(visibleConsoles(identity("admin")), [
    "console-curator", "console-reviewer", "console-corpus", "console-auditor",
    "console-accounts",
  ]);
});

test("roles compose rather than override", () => {
  assert.deepEqual(visibleConsoles(identity("curator", "auditor")), [
    "console-curator", "console-corpus", "console-auditor",
  ]);
});

test("an unknown role grants nothing", () => {
  assert.deepEqual(visibleConsoles(identity("commander")), []);
  assert.equal(permissionsOf(identity("commander")).size, 0);
});

test("no identity means no console, not every console", () => {
  assert.deepEqual(visibleConsoles(null), []);
  assert.equal(permits(null, "document:ingest"), false);
});

test("the role table is the generated one, not a second copy", () => {
  // If this drifts from policy.py, `make web-contract` regenerates it and the pipeline's
  // --check fails first. The assertion here is that the module reads that table at all.
  assert.deepEqual([...permissionsOf(identity("curator"))].sort(), CONTRACT.roles.curator);
});

// ------------------------------------------------------------ validation

test("a note shorter than the contract's minimum never leaves the browser", () => {
  const problems = reviewProblems({target: "approved", note: "коротко"}, "v1");
  assert.equal(problems.length, 1);
  assert.match(problems[0], /^note: щонайменше 12 символів, зараз 7$/);
});

test("a note at exactly the minimum passes", () => {
  assert.deepEqual(reviewProblems({target: "approved", note: "рівно дванадц"}, "v1"), []);
});

test("a missing version id is refused with the field named", () => {
  const problems = reviewProblems({target: "approved", note: "достатньо довге обґрунтування"}, "");
  assert.deepEqual(problems, ["ідентифікатор версії: обов'язковий"]);
});

test("a target outside the contract's enum is refused", () => {
  const problems = reviewProblems(
    {target: "archived", note: "достатньо довге обґрунтування"}, "v1");
  assert.deepEqual(problems, ["target: значення поза переліком ReviewState"]);
});

test("setting a tier on a non-approval is refused before the round trip", () => {
  // The server refuses it too. Saying so here means the operator does not learn it by
  // submitting a decision.
  const problems = reviewProblems(
    {target: "rejected", note: "достатньо довге обґрунтування", access_tier: 2}, "v1");
  assert.deepEqual(problems, ["рівень доступу задається лише при затвердженні"]);
});

test("a tier on an approval is accepted", () => {
  assert.deepEqual(
    reviewProblems({target: "approved", note: "достатньо довге обґрунтування", access_tier: 2}, "v1"),
    [],
  );
});

test("an ingestion without a file is refused", () => {
  assert.deepEqual(ingestProblems(validDocument, validVersion, false), ["файл джерела: обов'язковий"]);
});

test("a complete ingestion passes", () => {
  assert.deepEqual(ingestProblems(validDocument, validVersion, true), []);
});

test("a corpus id that breaks the pattern is refused with the pattern shown", () => {
  const problems = ingestProblems({...validDocument, corpus_id: "Public Corpus"}, validVersion, true);
  assert.equal(problems.length, 1);
  assert.match(problems[0], /^corpus_id: не відповідає /);
});

test("a title below the minimum length is refused", () => {
  const problems = ingestProblems({...validDocument, canonical_title: "ab"}, validVersion, true);
  assert.deepEqual(problems, ["canonical_title: щонайменше 3 символів, зараз 2"]);
});

test("a title above the maximum length is refused", () => {
  const problems = ingestProblems(
    {...validDocument, canonical_title: "я".repeat(501)}, validVersion, true);
  assert.deepEqual(problems, ["canonical_title: щонайбільше 500 символів, зараз 501"]);
});

test("every problem is reported, not just the first", () => {
  const problems = ingestProblems(
    {...validDocument, canonical_title: "", issuer: ""}, {revision: ""}, false);
  assert.equal(problems.length, 4);
});

test("an optional field left empty is not a problem", () => {
  assert.deepEqual(
    rescissionProblems({note: "достатня підстава для скасування"}, "v1"), []);
});

test("an optional field that is present is still checked", () => {
  // publication_identifier is `anyOf: [string, null]`. Reading maxLength off the union
  // finds nothing and emits an unconstrained field — the permissive direction, and the
  // one that produces a 422 an operator cannot predict.
  const problems = ingestProblems(
    validDocument, {...validVersion, publication_identifier: "n".repeat(201)}, true);
  assert.deepEqual(problems, ["publication_identifier: щонайбільше 200 символів, зараз 201"]);
});

test("a model with no generated constraints raises rather than passing everything", () => {
  assert.throws(() => validateAgainst("DocumentRecord", {}), /no generated constraints/);
});

// ------------------------------------------------------------ preview gating

test("an unpreviewed submission does not match", () => {
  assert.equal(previewMatches(null, {a: 1}), false);
});

test("a previewed submission matches itself", () => {
  const body = {target: "approved", note: "достатньо довге обґрунтування"};
  assert.equal(previewMatches(JSON.stringify(body), body), true);
});

test("editing after the preview breaks the match", () => {
  const previewed = JSON.stringify({target: "approved", note: "достатньо довге обґрунтування"});
  assert.equal(
    previewMatches(previewed, {target: "rejected", note: "достатньо довге обґрунтування"}), false);
});

test("a version id swapped after the preview breaks the match", () => {
  // The failure the gate exists for: an approval previewed against one version and
  // submitted against another.
  const first = {target: "approved", note: "достатньо довге обґрунтування", version: "a"};
  assert.equal(previewMatches(JSON.stringify(first), {...first, version: "b"}), false);
});

// ------------------------------------------------------------ consequences

test("approval is described as making the version citable, not as a state change", () => {
  const text = reviewConsequence({target: "approved", note: "x".repeat(12)});
  assert.match(text, /придатною до цитування/);
  assert.match(text, /не редагуються/);
});

test("rejection and approval do not read the same", () => {
  const approved = reviewConsequence({target: "approved", note: "x".repeat(12)});
  const rejected = reviewConsequence({target: "rejected", note: "x".repeat(12)});
  assert.notEqual(approved, rejected);
});

test("a tier change is named in the consequence when one is set", () => {
  assert.match(
    reviewConsequence({target: "approved", note: "x".repeat(12), access_tier: 3}),
    /Рівень доступу встановлюється на 3/,
  );
  assert.doesNotMatch(
    reviewConsequence({target: "approved", note: "x".repeat(12)}),
    /Рівень доступу встановлюється/,
  );
});

test("every reviewable target has its own sentence", () => {
  const described = CONTRACT.enums.ReviewState
    .filter(state => state !== "quarantined")
    .map(state => reviewConsequence({target: state, note: "x".repeat(12)}));
  assert.equal(new Set(described).size, described.length);
  for (const text of described) assert.doesNotMatch(text, /^стан змінюється/);
});

test("ingestion says the version lands in quarantine, not that it is published", () => {
  const text = ingestConsequence({document: validDocument, version: validVersion});
  assert.match(text, /карантину/);
  assert.match(text, /лише після затвердження/);
});

test("rescission distinguishes an immediate withdrawal from a dated one", () => {
  assert.match(rescissionConsequence({note: "x".repeat(12)}), /негайно/);
  assert.match(
    rescissionConsequence({note: "x".repeat(12), rescinded_at: "2026-08-05T00:00:00.000Z"}),
    /від 2026-08-05T00:00:00\.000Z/,
  );
});

// ---------------------------------------------------------------- accounts
//
// Switching a person off is the one console action whose subject is a person rather than
// a document. The consequence line is tested as carefully as the validation, because it
// is the last thing between an operator at three in the morning and somebody losing
// access to the manuals they need in the next hour.

test("only an administrator sees the accounts console", () => {
  assert.ok(visibleConsoles(identity("admin")).includes("console-accounts"));
  for (const role of ["curator", "reviewer", "auditor", "user", "instructor"]) {
    assert.ok(
      !visibleConsoles(identity(role)).includes("console-accounts"),
      `${role} was shown the accounts console`,
    );
  }
});

test("a status change is refused before it leaves without an account, a state and a reason", async () => {
  const {accountStatusProblems} = await import("../public/console_rules.js");
  const fields = accountStatusProblems({}).map(problem => problem.field);
  assert.deepEqual(fields.sort(), ["account-id", "account-reason", "account-status"]);

  assert.deepEqual(
    accountStatusProblems({account_id: "a", status: "disabled", reason: "скомпрометовано"}),
    [],
  );
});

test("a reason too short to mean anything is refused in the browser too", async () => {
  const {accountStatusProblems, MINIMUM_ACCOUNT_REASON} =
    await import("../public/console_rules.js");
  for (const reason of ["", "  ", "test", "x".repeat(MINIMUM_ACCOUNT_REASON - 1)]) {
    const problems = accountStatusProblems({account_id: "a", status: "disabled", reason});
    assert.ok(
      problems.some(problem => problem.field === "account-reason"),
      `${reason!==""?reason:"(порожньо)"} was accepted as a reason`,
    );
  }
});

test("an unknown state is refused rather than sent", async () => {
  const {accountStatusProblems} = await import("../public/console_rules.js");
  const problems = accountStatusProblems(
    {account_id: "a", status: "deleted", reason: "видалити назавжди"},
  );
  assert.ok(problems.some(problem => problem.field === "account-status"));
});

test("the consequence says what a person loses, without softening it", async () => {
  const {accountConsequence} = await import("../public/console_rules.js");
  const text = accountConsequence(
    {status: "disabled", reason: "скомпрометовано"},
    {ownSubject: "oidc|admin", targetSubject: "oidc|soldier"},
  );
  assert.match(text, /негайно втрачає доступ/);
  assert.match(text, /Розмови не видаляються/);
  assert.match(text, /аудиту/);
  assert.match(text, /oidc\|soldier/);
});

test("enabling says it restores and widens nothing", async () => {
  const {accountConsequence} = await import("../public/console_rules.js");
  const text = accountConsequence({status: "active"}, {targetSubject: "oidc|soldier"});
  assert.match(text, /нічого не розширює/);
  assert.doesNotMatch(text, /втрачає доступ/);
});

test("choosing your own account is named before the server refuses it", async () => {
  const {accountConsequence} = await import("../public/console_rules.js");
  const text = accountConsequence(
    {status: "disabled"}, {ownSubject: "oidc|admin", targetSubject: "oidc|admin"},
  );
  assert.match(text, /ваш власний акаунт/);
});
