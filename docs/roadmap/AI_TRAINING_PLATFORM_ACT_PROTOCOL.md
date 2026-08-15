# KORPUS — AI Training Platform Integration ACT Protocol

Status: PLANNED / NOT EXECUTED
Branch: `protocol/ai-training-platform-act`
Base: current KORPUS security-development head

## 0. Source concept

The product concept defines one platform with two separate user modes over a shared verified knowledge substrate:

1. **AI Assistants** — specialty-scoped question/answer interfaces for fast access to verified knowledge.
2. **AI Instructors** — structured learning runtimes that move a learner through course → modules → lessons → checks → final exam.

The two modes share trusted source material but have different contracts, state and success criteria.

---

## 1. Single target state

KORPUS exposes a verified, authorization-aware learning subsystem in which:

- each assistant answers only from its assigned corpus/scope;
- each instructor executes a versioned course graph;
- lesson explanations remain grounded in approved lesson/corpus evidence;
- assessments are served from expert-approved banks;
- learner progress, mastery and completion are persisted and auditable;
- rescinded/expired source material becomes unavailable to both Q&A and learning flows;
- all course, assessment and certificate decisions are reproducible from persisted state;
- security classification, clearance, compartment and corpus restrictions are enforced by the same authorization substrate as the rest of KORPUS.

## 2. Initial state

KORPUS already has the architectural substrate needed for a large part of the feature family:

- verified corpus/evidence model;
- versioned documents and evidence spans;
- retrieval and answer runtime;
- review/approval provenance;
- temporal corpus snapshot/release identity work;
- PostgreSQL RLS / scoped authorization work;
- audit and production-assurance infrastructure.

Missing product-layer capabilities are course graphs, learner state, assessment banks, mastery calculations, instructional runtime, learning telemetry, portable completion credentials and offline learning synchronization.

## 3. Constraints

1. **No second truth store for knowledge.** Courses reference versioned KORPUS content/evidence rather than copying authoritative material into opaque prompts.
2. **No LLM-authored authoritative answers.** Generated explanations may rephrase approved evidence but may not create new normative content.
3. **Assessment correctness is deterministic.** Correct answers, scoring rules and pass criteria are persisted/versioned and expert-approved.
4. **Authorization is inherited, not bypassed.** Learning features must use canonical corpus/classification/compartment policy.
5. **Temporal consistency.** A lesson/session/exam records the exact release/snapshot from which content was served.
6. **Fail closed.** Missing source, expired source, insufficient clearance, invalid course version or unverifiable assessment state blocks the operation.
7. **Observable behavior only.** No task may be closed by prose, screenshots or static inspection alone when executable verification is possible.
8. **No certification claim before evidence.** “Certified”, “qualified”, “competent” or equivalent product language requires an explicit externally accepted credentialing policy.

## 4. Observable success criterion

The integration is considered implemented only when an end-to-end PostgreSQL scenario proves, with exit code 0 and persisted evidence, that one authorized learner can:

`select specialty → enter assistant → receive grounded answer → enroll in course → complete versioned lesson → ask in-lesson grounded question → pass intermediate assessment → complete final exam → obtain completion record`

while parallel destruction tests prove that an unauthorized learner cannot access restricted course content, infer hidden assessment content, forge progress, forge mastery, alter scoring, or mint a completion credential.

---

# ACT TASK REGISTER

Each ACT has: **Intent → State Transition → Acceptance → Evidence → Kill Condition**.

## ACT-LRN-001 — Specialty-scoped Assistant Registry

**Intent**
Create explicit assistant definitions instead of one universal chat.

**State transition**
`generic_answer_runtime → assistant_id + specialty + allowed_corpora + allowed_content_types + policy_profile`

**Acceptance**
- assistant has immutable/versioned scope definition;
- retrieval cannot escape assigned corpus/specialty boundary;
- answer provenance records assistant + corpus release + evidence ids;
- unsupported questions abstain or route explicitly, never silently broaden scope.

**Evidence**
Integration tests across at least two specialties with cross-scope denial controls.

**Kill condition**
If assistant identity does not change retrieval authorization behavior, the registry is decorative and must not ship.

## ACT-LRN-002 — Course Domain Model

**Intent**
Represent structured instruction as first-class persisted data.

**Entities**
- Course
- CourseVersion
- Module
- Lesson
- LessonBlock
- LearningObjective
- Prerequisite
- SourceBinding
- CoursePublicationState

**Acceptance**
- course graph is versioned;
- published version is immutable;
- lessons bind to exact approved KORPUS source/evidence;
- source rescind/expiry invalidates affected lesson publication until re-reviewed;
- graph validation rejects cycles where forbidden and dangling prerequisites/source references.

**Evidence**
Schema migrations + domain tests + PostgreSQL publication/destruction tests.

## ACT-LRN-003 — AI Instructor Runtime

**Intent**
Create a stateful instructional runtime distinct from general Q&A.

**Runtime state**
`learner + course_version + module + lesson + release_id + progress_state + mastery_state`

**Acceptance**
- instructor is aware of current lesson/objectives;
- explanations are grounded only in lesson/course-approved sources;
- responses cite or internally bind exact evidence;
- runtime cannot advance locked prerequisites;
- source/release drift forces a controlled rebind/revalidation rather than silent continuation.

**Evidence**
Deterministic scenario tests and adversarial attempts to make the instructor answer outside lesson scope.

## ACT-LRN-004 — Expert-approved Assessment Bank

**Intent**
Separate generated wording from authoritative scoring truth.

**Entities**
- QuestionBank
- QuestionVersion
- AnswerOption
- ScoringRule
- Rubric
- ApprovalRecord
- Difficulty/Objective tags

**Acceptance**
- only approved question versions are eligible for scored exams;
- correct answer/rubric cannot be modified by ordinary learner/runtime identity;
- question selection is reproducible from exam seed/version;
- order randomization does not change semantic scoring;
- invalidated source invalidates dependent assessment items.

**Evidence**
Mutation tests against answer key, pass threshold, randomization and question-version pinning.

## ACT-LRN-005 — Intermediate Checks

**Intent**
Implement short checks after learning blocks.

**Acceptance**
- configurable item count and pass threshold;
- deterministic scoring;
- attempt history persisted;
- remediation path records weak objectives;
- retake policy is explicit and versioned.

**Evidence**
Boundary tests: exactly below threshold, exactly at threshold, repeated attempt, changed course version.

## ACT-LRN-006 — Final Exam Runtime

**Intent**
Provide controlled final assessment.

**Acceptance**
- exam blueprint specifies question pool, selection policy, duration, pass criteria and retake policy;
- exam instance freezes blueprint + course version + selected question versions + seed + timestamps;
- server-side time enforcement;
- final result is recomputable from immutable answers and scoring rules;
- learner cannot submit/alter another learner’s exam.

**Evidence**
Replay verification and IDOR/tampering/concurrency tests.

## ACT-LRN-007 — Learner Progress Ledger

**Intent**
Persist progress as auditable state, not UI state.

**Entities**
- Enrollment
- LessonProgress
- Attempt
- CompletionEvent
- ProgressVersion

**Acceptance**
- monotonic events are append/audit anchored where appropriate;
- derived percentage is recomputable;
- no client-controlled completion mutation;
- course-version changes have explicit migration/re-enrollment semantics.

**Evidence**
Replay from events to exact current progress + forged-client-state rejection.

## ACT-LRN-008 — Competency / Mastery Graph

**Intent**
Map lessons and assessments to measurable objectives/competencies.

**Acceptance**
- explicit objective IDs;
- evidence-backed mastery inputs;
- deterministic base mastery model before any adaptive/ML layer;
- mastery output includes uncertainty/evidence count;
- no “competent” label without configured policy threshold.

**Evidence**
Golden fixtures where mastery is exactly recomputed from persisted attempts.

## ACT-LRN-009 — Adaptive Remediation

**Intent**
Recommend what to repeat based on observed weak objectives.

**Acceptance**
- recommendation inputs are inspectable;
- recommendation never modifies authoritative course order without policy permission;
- fallback is deterministic;
- recommendation can be disabled without breaking course completion.

**Evidence**
A/B or offline evaluation only after deterministic baseline exists.

**Kill condition**
If adaptive policy cannot outperform the deterministic prerequisite/weak-objective baseline on a preregistered metric, keep the baseline.

## ACT-LRN-010 — Spaced Repetition Scheduler

**Intent**
Schedule review of previously learned material.

**Acceptance**
- deterministic scheduling algorithm/version;
- due items derive from attempts/mastery timestamps;
- no hidden model dependency required for correctness;
- learner can inspect why an item is due.

**Evidence**
Clock-controlled tests and schedule replay.

## ACT-LRN-011 — Lesson Notes / Personal Learning Memory

**Intent**
Allow personal notes without contaminating authoritative knowledge.

**Acceptance**
- notes are user-private by default;
- notes are never retrieved as authoritative corpus evidence;
- user may explicitly search/export/delete their own notes;
- permissions prevent cross-user leakage.

**Evidence**
Tenancy and retrieval-poisoning tests.

## ACT-LRN-012 — SME / Instructor Console

**Intent**
Give subject-matter experts controlled publishing workflows.

**Functions**
- draft/edit course;
- bind approved sources;
- review lesson;
- approve/reject assessment items;
- publish/withdraw course version;
- review learner aggregate analytics where policy permits.

**Acceptance**
No publication, answer-key change or scoring-policy change is possible through ordinary application identity.

**Evidence**
Split-role PostgreSQL authorization tests.

## ACT-LRN-013 — AI Course Builder

**Intent**
Use AI to accelerate draft production without granting it publication authority.

**Acceptance**
- generates drafts only;
- every generated claim must map to available source evidence or be flagged unsupported;
- generated questions remain unscored/unpublished until human approval;
- source coverage report is attached to draft.

**Kill condition**
If unsupported-claim rate cannot be measured, builder cannot enter controlled production.

## ACT-LRN-014 — Learning Analytics

**Intent**
Expose operational learning metrics.

**Minimum metrics**
- enrollment/completion;
- lesson progress;
- assessment attempts/pass rates;
- objective-level error distribution;
- time-to-completion;
- retention/review due state.

**Acceptance**
Metrics are derived from canonical learner ledger, not separate mutable counters.

## ACT-LRN-015 — xAPI / Learner Record Store Boundary

**Intent**
Provide interoperable learning-event export/import boundary.

**Target**
Adopt xAPI-compatible event semantics and an LRS boundary only after internal event contracts stabilize.

**Acceptance**
- internal events map deterministically to xAPI statements;
- duplicate delivery is idempotent;
- source event id remains traceable;
- external LRS failure cannot corrupt internal learner state.

**Reference**
ADL xAPI / Total Learning Architecture service definitions.

## ACT-LRN-016 — cmi5 Course Package Interoperability

**Intent**
Allow standards-based packaged learning content where useful.

**Acceptance**
- parser treats imported packages as untrusted input;
- import cannot bypass KORPUS source-review or authorization policy;
- imported launch/completion events map to canonical learner state through an explicit adapter.

**Reference**
ADL cmi5.

## ACT-LRN-017 — CASE Competency Interoperability

**Intent**
Allow competency frameworks to map to external standardized identifiers.

**Acceptance**
Internal objective IDs remain canonical; CASE mappings are versioned external references, not the truth store.

**Reference**
1EdTech CASE.

## ACT-LRN-018 — Verifiable Completion Record

**Intent**
Issue a machine-verifiable course completion artifact.

**Acceptance**
- credential binds learner identity, course version, exam/result, issuer and timestamp;
- credential is signed by a release/credential key isolated from application runtime;
- revocation/status semantics exist;
- completion record must not imply external professional certification unless separately authorized.

**Reference**
1EdTech Open Badges 3.0 / CLR-compatible direction.

## ACT-LRN-019 — Offline-first Learning Package

**Intent**
Support intermittent connectivity without weakening source/version integrity.

**Acceptance**
- signed offline package binds course version + source release + expiry;
- local progress events are append-only and uniquely identified;
- synchronization is idempotent and conflict-explicit;
- offline client cannot mint passed exams or completion credentials locally;
- revoked course/package is rejected on reconnect according to explicit policy.

**Evidence**
Network-loss, replay, clock-skew, duplicate-sync and tampering tests.

## ACT-LRN-020 — Multilingual Learning Layer

**Intent**
Support Ukrainian/English presentation without creating divergent truths.

**Acceptance**
- translation is bound to canonical source/lesson version;
- translated assessment item has its own review state;
- scoring semantics are shared or explicitly versioned;
- missing approved translation falls back visibly rather than machine-translating scored material silently.

## ACT-LRN-021 — Assistant ↔ Instructor Routing

**Intent**
Expose two modes cleanly over one substrate.

**Acceptance**
- assistant mode answers a concrete question;
- instructor mode maintains course state;
- explicit user action can move from assistant discovery to a relevant course;
- instructor may call grounded explanation inside current lesson;
- modes cannot silently share mutable prompt memory that changes authorization or scoring.

## ACT-LRN-022 — Personal Learning Path Planner

**Intent**
Create an inspectable plan from prerequisites, completed objectives and target course.

**Acceptance**
First production version is deterministic graph planning. Any ML/LLM planner is advisory until it beats the baseline on preregistered completion/efficiency metrics without increasing policy violations.

## ACT-LRN-023 — Knowledge-gap Detector

**Intent**
Identify unsupported or weakly covered course objectives.

**Acceptance**
For every learning objective, report:
- bound approved sources;
- assessment coverage;
- stale/rescinded dependencies;
- unsupported objective flag;
- minimum evidence coverage threshold.

A published course cannot contain a critical objective with zero approved evidence coverage.

## ACT-LRN-024 — Authorization-aware Course Access

**Intent**
Make course visibility and lesson retrieval obey the same policy substrate as corpus access.

**Acceptance**
- course listing is filtered before pagination/limits;
- lesson source access is checked at read time;
- assessment metadata does not leak restricted specialty/content;
- clearance/compartment changes take effect without stale cached access.

**Evidence**
PostgreSQL RLS tests across course, lesson, assessment, progress and analytics boundaries.

## ACT-LRN-025 — Learning Audit Trail

**Intent**
Make all high-impact learning decisions attributable and replayable.

**Events**
- course publish/withdraw;
- source binding changes;
- assessment approval/key changes;
- exam start/submit/score;
- completion/revocation;
- credential issuance/revocation;
- privileged learner-state correction.

**Acceptance**
Every event records actor, authority, object/version, timestamp and integrity binding.

## ACT-LRN-026 — Blended Training / Scheduling Adapter

**Intent**
Represent instructor-led sessions without making calendar integration part of core correctness.

**Acceptance**
Session attendance is a versioned learning event; external calendar is an adapter, not the source of truth.

## ACT-LRN-027 — Agentic LMS Orchestration (late-stage)

**Intent**
Automate low-risk learning workflow steps after deterministic APIs exist.

**Allowed initial actions**
- recommend next lesson;
- prepare revision set;
- summarize learner-visible progress;
- locate approved resources.

**Forbidden without explicit authorization**
- publish content;
- alter answer keys;
- alter grades;
- waive prerequisites;
- issue credentials.

**Promotion condition**
Only after deterministic course, assessment, authorization and audit APIs are stable and executable safety tests exist.

---

# Implementation order

## Phase A — Substrate extension
1. ACT-LRN-002 Course Domain Model
2. ACT-LRN-024 Authorization-aware Course Access
3. ACT-LRN-025 Learning Audit Trail
4. ACT-LRN-001 Specialty-scoped Assistant Registry

## Phase B — Deterministic learning core
5. ACT-LRN-007 Learner Progress Ledger
6. ACT-LRN-004 Expert-approved Assessment Bank
7. ACT-LRN-005 Intermediate Checks
8. ACT-LRN-006 Final Exam Runtime
9. ACT-LRN-003 AI Instructor Runtime
10. ACT-LRN-021 Assistant ↔ Instructor Routing

## Phase C — Measurement and adaptation
11. ACT-LRN-008 Competency / Mastery Graph
12. ACT-LRN-023 Knowledge-gap Detector
13. ACT-LRN-014 Learning Analytics
14. ACT-LRN-009 Adaptive Remediation
15. ACT-LRN-010 Spaced Repetition
16. ACT-LRN-022 Learning Path Planner

## Phase D — Authoring and learner experience
17. ACT-LRN-012 SME / Instructor Console
18. ACT-LRN-013 AI Course Builder
19. ACT-LRN-011 Lesson Notes
20. ACT-LRN-020 Multilingual Layer
21. ACT-LRN-019 Offline-first Learning

## Phase E — Interoperability and credentials
22. ACT-LRN-015 xAPI/LRS Boundary
23. ACT-LRN-016 cmi5 Adapter
24. ACT-LRN-017 CASE Mapping
25. ACT-LRN-018 Verifiable Completion Record
26. ACT-LRN-026 Blended Training Adapter
27. ACT-LRN-027 Agentic LMS Orchestration

---

# Cross-cutting production gates

Every ACT promoted to production must provide applicable evidence from this set:

1. unit/domain tests;
2. PostgreSQL integration tests;
3. authorization/RLS destruction tests;
4. temporal snapshot/release consistency tests;
5. mutation controls for scoring/authorization logic;
6. audit replay;
7. concurrency/idempotency tests;
8. migration upgrade/downgrade or forward-only recovery evidence;
9. module-budget/lint/type gates;
10. production-assurance artifact bound to exact source digest/release.

A task is **not complete** when only code, documentation, mock screenshots or unexecuted tests exist.

# Global fail-closed invariants

- `ANSWERED => evidence is authorized + approved + temporally valid`
- `LESSON_SERVED => course_version is published + source bindings are valid`
- `SCORED => question_version + scoring_rule_version are approved and immutable for the attempt`
- `COMPLETED => all mandatory prerequisites + assessments satisfy the frozen course-version policy`
- `CREDENTIAL_ISSUED => canonical completion record exists and verifies`
- `RESTRICTED => unauthorized users cannot discover content through listing, search, counts, timing or metadata`

# Non-goals for first production slice

- autonomous AI certification decisions;
- autonomous publication of generated military instruction;
- opaque ML mastery scoring;
- real-time tactical command/decision automation;
- unrestricted cross-specialty agent behavior;
- replacing instructors/SMEs as source approvers.

# First executable slice

The first implementation slice is deliberately small:

`ACT-LRN-002 + ACT-LRN-024 + ACT-LRN-007 + ACT-LRN-004 + ACT-LRN-005 + ACT-LRN-003`

One specialty, one published course, one module, several lessons, one approved question bank, one intermediate test, one learner, one authorized/one unauthorized identity.

Promotion requires a real PostgreSQL E2E run and destruction controls. Until then:

`IMPLEMENTATION=NOT_STARTED`
`EXECUTABLE_EVIDENCE=NONE`
`PRODUCTION_GATE=FAIL`
