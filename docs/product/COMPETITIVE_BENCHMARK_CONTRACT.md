# KORPUS competitive benchmark contract

## Purpose

KORPUS competes on verified task completion under controlled evidence, not on fluent prose,
feature count, course completion, or vendor benchmark claims. A comparison is valid only when
systems receive the same frozen cases, authorized corpus snapshot, time budget and disclosure
policy. The harness, dataset hash, system revision and resource budget must accompany results.

## Benchmark slices

Every release dataset must stratify by role, task, risk, language, source authority, temporal
state, access tier, expected answer/abstention, connectivity mode and document layout. Hidden
evaluation cases remain separate from development cases. A human-reviewed case records the
question, permitted evidence, required claims, forbidden claims and valid decision set.

## Lexicographic gates

Safety is not exchanged for speed or answer rate. Candidate systems are compared in this order:

1. zero unauthorized materialization events;
2. zero citations outside source validity or exact evidence boundaries;
3. zero unsupported critical claims;
4. non-inferior task success and calibrated abstention on the locked set;
5. only then: lower latency, external calls, tokens, searches and monetary cost.

A failure in gates 1–3 disqualifies a build. Gate 4 requires confidence intervals and paired
case analysis; a point estimate is insufficient. Performance wins are reported per slice, not
silently averaged across easy and critical cases.

## Learning effectiveness

Course completion is an activity measure, not competence. The learning benchmark measures:

- coverage of every competency required by a selected role and operational task;
- scenario assessment against explicit conditions and observable standards;
- delayed retention and transfer to novel but doctrine-equivalent cases;
- revocation and reassessment after a bound source changes;
- time to correct action, error severity and justified abstention under stress-oriented UX.

The first executable invariant is implemented by
`korpus.domain.operational_competency.validate_course_alignment`. It uses conjunctive task
coverage and rejects unknown graph edges. Persistence, reviewer lifecycle, scenario evidence and
external interoperability are subsequent vertical slices; this contract does not pretend they
already exist.

## Prohibited benchmark practices

- no tests written after seeing a competitor's hidden answers;
- no different corpora, permissions or compute budgets between systems;
- no treating a citation marker as proof that the cited span supports the claim;
- no replacing abstentions with plausible prose to improve answer rate;
- no transferring published vendor gains to KORPUS without reproduction;
- no claiming qualification from completion, self-report or one multiple-choice attempt.
