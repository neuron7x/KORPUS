# KORPUS v5 — residual debt contract

> **Заморожений знімок v5 (2026-08-05).** Числа тут описують стан на момент v5 і
> застаріли: наприклад «31 EXTERNAL_DEBT» стосується v5, тоді як поточний реєстр має 9.
> Поточні цифри, по яких ухвалюють допуск, — у `docs/operations/CURRENT_STATUS.md`,
> згенерованому з реєстрів і покритому parity-тестом. Цей документ лишається як історія.


This document records work that cannot be converted into PASS by local code or synthetic tests.

## Frozen audit debt counts (reclassified 2026-08-05)

- 75/99 findings remain non-closed in the frozen audit scope.
- 44 are `MITIGATED_LOCAL`: a material local control exists, but external/live acceptance remains.
- 31 are `EXTERNAL_DEBT`: they require independent people, systems, infrastructure or authorization.
- 0 are `OPEN_TECH_DEBT`, as of the second pass on 2026-08-05.

An empty `OPEN_TECH_DEBT` is not an empty debt list. Nothing was deleted: COD-001,
WEB-001 and OPS-004 moved to `MITIGATED_LOCAL`, which means a control now exists and
runs, and the part that remains is named below rather than counted as finished. The
thirty-one `EXTERNAL_DEBT` findings are untouched by any of this — no code in this tree
can close them, and `production_authorized` stays false.

The counts above were stale for a day. `build_audit_closure.py` classifies by a static
set, so nine findings closed or mitigated on 2026-08-05 still read as open engineering
debt while the register reported on them — a document about closure that had not closed
its own loop. Every move carries the test that fails without the fix and, where the
finding is about code, the mutant that removes it and dies. Three moved to
`CLOSED_LOCAL` (SUP-002 hashed locks, COD-002 validator complexity, COD-003 broad
handlers) and six to `MITIGATED_LOCAL`, where the residue is external or partial and
is named below rather than counted as finished:

| finding | closed here | what remains |
|---|---|---|
| RAG-013 | numbers, units, table structure | formula structure |
| RAG-017 | embedding drift, four states | online answer-quality monitoring |
| INF-009 | telemetry reports REQUESTED_NOT_ACTIVE | a durable telemetry backend |
| SUP-009 | 68/68 licenses from metadata | legal review |
| COD-004 | branch coverage 0.7726, gated where produced | the 0.13 gap to line coverage |
| AUD-004 | resumable, gap-evident export | the SIEM that receives it |

SUP-001 closed later the same day: every image in the pipeline, the compose file and
both Dockerfiles is pinned by digest with its tag kept beside it for readability. The
concrete cost of tags had shown up hours earlier, when a kaniko version that does not
exist reached a queued pipeline — a digest cannot be invented, and cannot be repointed
at different bytes afterwards.

RAG-009 followed: the risk classifier is a register of rules carrying ids, rationales
and their own examples, and an unmatched query is UNCLASSIFIED rather than STANDARD.
Two defects sat behind that finding and only one was about regular expressions. The
second was direction: an unrecognised query fell to the loosest evidence thresholds in
the system, which is fail-open in the one place this design is otherwise fail-closed.
UNCLASSIFIED is now scored at the temporal setting — stricter than ordinary, not so
strict that operators learn to ignore refusals. What stays open is the acceptance
predicate the audit actually states: a trained classifier on a blind set with per-class
precision, recall and worst-group metrics, which needs annotated queries nobody here
has. That is `MITIGATED_LOCAL`, not closed.

COD-001 moved in four steps and is now `MITIGATED_LOCAL`. `SqlRepository` was 1855
lines; it is 1047. The audit read side went to `infrastructure/audit_reader.py`, the row
mappers to `row_mapping.py`, and on the second pass the physical schema to `schema.py`
and the retrieval projection to `retrieval_queries.py`.

The last of those is the one worth reading. Clearance, classification, compartment,
currency and supersession — the whole access decision at the retrieval layer — are now
in a module that constructs statements and never opens a connection, so a test can
compile the projection and read the predicates without a corpus behind it.
`test_repository_seams.py` holds that line structurally rather than behaviourally: a
builder that opened its own connection would bypass `_apply_postgres_identity`, the call
that sets the PostgreSQL row-level security context, and no behavioural test on SQLite
would notice, because SQLite has no RLS to bypass.

What remains, and why the finding is not `CLOSED_LOCAL`: the acceptance predicate is
"each module has one responsibility", and the 1047 lines left still carry CRUD, review
transitions, audit append, readiness and the RLS session context. Those cannot be split
without splitting a transaction — `create_version_bundle` writes rows and their audit
event atomically, and an abstraction separating them would break that atomicity or leak
it. Cutting where the class does not part would be the same debt in more files.

The split also found a defect it had itself created, and this is the part that argues
for mutation testing over reading. `M05_SQL_CLEARANCE_FILTER_REMOVED` had always passed.
Its target string, `.where(documents.c.access_tier <= int(identity.clearance))`,
appeared *twice* in one file — in the retrieval projection and in `list_documents` — so
a single substitution mutated both, and a retrieval test killed it. Moving the
projection out left the listing predicate alone in `repository.py`, the mutant applied
only there, and it survived: `list_documents` would have returned every document in a
reader's corpora at any tier, and nothing in the suite objected. Two occurrences under
one mutant is not two covered call sites. Fixed by
`test_listing_hides_a_document_above_the_readers_clearance` and mutant M130.

The extraction cost six mutants their targets and they went INVALID — the documented
behaviour, and the reason it is a gate. It also exposed a defect one level up: the
failed mutation run left its previous report in place, so the operational gate read
evidence from a tree that no longer existed and reported "generated from a different
source tree" — accurate, and three steps from the cause. A failed run now removes its
report: absent evidence and stale evidence must not be the same state.

RAG-016 followed: `application/embedding_migration.py` plans a blue-green move as
resumable batches and states what may not happen before what. The failure it prevents
is not a slow migration but a *mixed* one — retrieval filters vectors by model id, so
during a re-embed the active model covers a moving subset of the corpus, every answer
comes from a candidate set the calibrated profile never described, and nothing reports
an error because a filter that matches nothing is not an error. The switch requires
100% coverage and no stale vectors, which is the finding's own acceptance predicate;
retire happens only after the switch, because the old population is the only thing that
can answer while the new one is incomplete; and rollback availability is checked before
it is needed rather than during an incident. Executing the plan against a real index
and embedding service is external evidence, so this is MITIGATED_LOCAL. Mutants
M153–M155.

WEB-001 followed: `apps/web/public/console.html` carries role-specific consoles for
ingestion, durable-job status, quarantine review, approval, rescission, corpus listing,
span reading and audit inspection, so the acceptance predicate — every critical workflow
executable without raw DB or API manipulation — is met by the surface that exists.

Three properties make that safe rather than merely possible. Nothing irreversible fires
on a first click: each writing workflow has a preview that renders the exact payload and
what it will do to the corpus, submit ships disabled, and the submit path re-compares
the serialised body rather than trusting a "was previewed" flag — an approval previewed
against one version id and submitted against another is the failure being prevented. A
refusal is rendered verbatim with its status, because "something went wrong" is what
sends an operator back to psql. And the field constraints and the role table are
*generated* from `contracts/openapi.json` and `policy.py` by
`scripts/generate_web_contract.py`, drift-gated in the pipeline: a hand-written copy of
`minLength: 12` is a second copy of the domain rules, and the copy drifts silently in
the direction nobody reports — a form refusing what the API would accept.

Which console a role sees follows the permissions the server reported, and the page says
in its own text that hiding a control is not access control. The server refuses
regardless.

Building it exposed an inert gate. `node --check <file>` exits 0 for *any* file
containing an `import` statement — verified on node v22.23.1 against a file holding both
an import and `const y = ;`. Two such invocations were `npm run lint`, so from the moment
`app.js` became a module the web syntax check stopped checking and kept printing success.
The parse now happens inside `validate.mjs` on stdin with an explicit `--input-type`, and
`apps/web/tests/validate_gate.test.mjs` mutates a copy of the tree once per control —
twenty negative controls — so a check that has stopped checking fails instead of passing
quietly. A second control had the same shape: the persistent-storage scan matched the
bare word `localStorage` and therefore tripped on api.js's own comment explaining why a
token must never go there. A guard that forbids naming the hazard it guards against gets
the explanation deleted, not the hazard.

What remains for WEB-001, and why it is not `CLOSED_LOCAL`: a real Chromium/CDP
campaign now executes the rendered consumer and operator surfaces in a browser. It
covers authenticated product boot under a deterministic transport fixture, answer and
citation XSS escaping, typed 429 throttling, a 390 px mobile overflow invariant, and
admin/reviewer role visibility plus preview-before-submit. The report is explicitly
`LOCAL_BROWSER_POLICY_COMPATIBLE`: the verifier host enforces a browser URL block policy,
so it cannot prove network navigation, same-origin deployment, OIDC redirects or the
real session-cookie path. Those networked browser controls, plus full corpus and
entitlement administration, remain external product evidence; the local Chromium suite
is therefore evidence of DOM/wiring/security/mobile behavior, not production login E2E.

OPS-004 followed: `application/environment_drift.py` compares an observed environment
against `config/operations/desired-state-v5.json` and distinguishes four answers, not
two. `IN_SYNC` and `DRIFTED` are the obvious pair; `UNOBSERVED` is the one that matters
and the one that gets folded into "in sync" by accident, because a reconciler handed a
partial observation that reports no drift is reporting on whatever subset it happened to
see — and an artefact deleted from the cluster produces exactly that observation.
`EXTRA` is separate again: something running that nothing declared was never reviewed at
all, and calling that "drift" puts it in the same bucket as a version bump.

The check is deliberately two commands. `--observe` fingerprints a deployed tree on the
host that is running; `--observation` compares the result against the manifest as
committed. Doing both in one process on the build host would fingerprint the build host,
which is the failure the check exists to catch, performed by the checker. The pipeline
runs both against its own checkout: that proves the comparator works and that the
manifest describes this tree, and it is explicitly not evidence about a cluster.

What remains: taking the observation from a live cluster, and acting on the verdict.
Detection is here; "reverted/blocked" is the operator's half, and stays external like
every other integration with a system nobody here operates. Mutants M124–M129.

Machine-readable registers: `docs/audit/closure/KORPUS_v5_REMAINING_DEBT.json` and `.csv`.

## Domain-invariant debt (2026-08-04)

Eighteen of the twenty-seven canonical invariants recorded in
`docs/audit/INVARIANT_DIFF_2026-08-03.md` are closed by code, each with a failing test
and a mutant in `scripts/run_mutation_tests.py`. One is met by a stronger mechanism and
deliberately not ported verbatim. One — `superseded-never-current` — stays open: the
canonical reading takes an order out of force the moment anyone uploads a draft
successor, which is a denial of service triggered by ordinary work. It needs a process
owner's decision, not more code. Register: `docs/audit/INVARIANT_CLOSURE_2026-08-04.md`.

Closure was demonstrated on SQLite in the test profile. The PostgreSQL branches of the
validity queries, `pg_stat_database` checksum counting and `PRAGMA`-equivalent
integrity probing carry no executable evidence in that run — same category as the live
PostgreSQL debt below.

## External acceptance debt

- formal production and restricted-data authorization with a named risk owner;
- signed corpus rights, classification, releasability and data-owner manifests;
- independent TEVV, application pentest, AI red-team and parser/container assessment;
- live PostgreSQL/pgvector, Kubernetes, OIDC, S3 Object Lock, KMS/HSM and remote-anchor evidence;
- production load, soak, chaos, rollback, PITR and measured RTO/RPO;
- human gold dataset, blinded holdout and inter-annotator agreement;
- GitLab protected-branch/tag policy and trusted-runner evidence;
- signed build provenance, artifact signing and immutable registry promotion;
- on-call, incident exercises, SLO/error-budget operation and capacity ownership.

## Open engineering debt

- the transactional core of the SQL repository (1047 lines, down from 1855): CRUD,
  review transitions, audit append, readiness and the RLS session context still share
  one class, because splitting them splits a transaction;
- formula evaluation, and table structure recovered from PDF layout rather than flagged;
- deployment execution of the governed embedding backfill against the operational
  index remains external evidence; the repository now provides resumable batches,
  atomic receipts and an independent RLS-scoped model/dimension/text-hash coverage gate;
- corpus and entitlement administration in the web consoles; networked same-origin
  browser E2E through real OIDC/session cookies; broader contrast and focus-order
  validation against the rendered critical workflows;
- a durable telemetry backend and its retention;
- an environment observation taken from a live cluster, admission policy enforcing the
  drift verdict, and cost/capacity governance;
- legal review of the declared dependency licenses.

### Closed 2026-08-06 — architecture and catalogue validation

- **the layering was a document, not a check** — `docs/architecture/SYSTEM_V5.md`
  stated the layers and nothing read the import graph. It had drifted:
  `application/ingestion_jobs.py` imported `SqlRepository` and `SqlIngestionJobQueue`,
  `application/ingestion.py` imported the parser functions. Both are ports now
  (`Repository` already existed and went unused; `IngestionJobQueue` and `Extractor`
  are new), and `korpus/composition.py` is the composition root.

  The cost was never tidiness. `IngestionCoordinator` is where a job is created and its
  audit event appended — a rule about ordering — and testing it against the real
  SQLAlchemy classes needs a database. Whether untrusted bytes may be parsed in-process
  is an application decision, and testing it needed a parser binary, an OCR install and
  a fork. Both are now assertions about a value reaching a port.

  Three things fell out of doing it properly. A default argument cannot name an
  implementation — every attempt, module-level or deferred inside `__init__`, puts the
  edge back — so `extractor` is required. `ExtractedPage` moved to the domain, because
  while it lived in infrastructure the port could not name what it returns. And the
  first version of the port invented its own types; `mypy --strict` caught six
  mismatches, which is worse than no port at all.

  `test_architecture.py` reads the graph including deferred imports, since "resolve it
  lazily" is the shape the violation kept returning in. Probed against both forms.
- **three mutants were covering two call sites each** — the substitution replaces every
  occurrence of the target string, so a mutant whose line appears twice mutates both and
  is answered by whichever site its test reaches. The other is never individually
  falsified and the report credits a kill for it anyway. This is how M05 passed for
  months. Found: the malware scan on both ingestion paths (the *version* path — the
  easier surface, since the document already passed review — was uncovered), the
  per-version cap declared twice with production using neither, and the lease-ownership
  check guarding both `complete` and `fail`, where `complete` is the one that records a
  version as ingested from bytes nobody parsed. M180–M182, and three parity tests over
  the catalogue: no ambiguous target, every cited test exists, ids unique.
- **a misspelled environment variable silently left a control off** —
  `SettingsConfigDict(extra="ignore")` drops an unrecognised `KORPUS_*` name without a
  word. Measured: with `KORPUS_REQUIRE_SOURCE_SIGNATURE=true` set — singular, where the
  field is `require_source_signatures` — `Settings()` constructs cleanly and the
  requirement is off. The deployment reads correct in review. `extra="forbid"` cannot be
  the fix, because the backup, recovery and role-provisioning scripts own `KORPUS_*`
  names and share the process environment, so the namespace is checked against the
  settings fields plus a *declared* list of operational names. Refused at startup rather
  than warned about. Verified that no surface we deploy carries one: both overlays and
  all nine compose services clean.
- **two acknowledgements a transposition apart** — `transition_version` took
  `acknowledge_near_duplicate` and `acknowledge_extraction_quality` positionally. Both
  are a reviewer's assertion about what they inspected, both enter the audit chain under
  their name, and swapping them type-checks, succeeds, and records that they
  acknowledged something they never looked at. Keyword-only, with a rule over the whole
  public surface.
- **the answer was mutable** — the binding between the text and its citations is decided
  once, by the policy, and a mutable model let anything downstream change the sentence
  while keeping the citations that justified a different one. Frozen.
  `Citation.source_hash` was an unconstrained string while
  `DocumentVersionRecord.source_hash` had carried `^[a-f0-9]{64}$` since the beginning —
  on the field a reader uses to check the quote came from the document named. The test
  written for it *survived its mutant*: it fabricated `quote_hash`, so the model refused
  for a different reason and the assertion held either way. A refusal test satisfied by
  a different refusal asserts nothing about the one it names.
- **a dead script one keystroke from the live one** —
  `scripts/prepare_postgres_test_role.py` was a ten-line wrapper nothing invoked, beside
  `prepare_postgres_role.py` which CI runs twice. Deleted. `scripts/export_audit.py` was
  cited as AUD-004's evidence with no runner at all — a citation naming a file rather
  than a run — and now has a `make audit-export` target; its first execution produced 5
  chain-linked events. A parity test asserts every script is reachable from some runner.
- **two refusal paths with a raise site and no test** — compared every exception class
  against the ones the suite names. `IngestionJobConflict` and
  `RetrievalDeadlineExceeded`. The second is not the same as an outage: a timeout means
  part of the corpus *was* searched, so answering from what came back is the tempting
  behaviour, and the reason code has to let an operator tell "never ran" from "ran out
  of time".

Also checked and clean: 20 routes all exercised; 740 tests with no duplicate names and
none without an assertion beyond five deliberate "must not raise" duals; no mutable
default arguments; no untyped public parameter or return; 44 Makefile targets with no
missing prerequisite or script; the CI graph with no `needs` on a later stage and no
artefact with two producers; 319 requirements across four registers with no duplicate id
and no statement written twice.

### Closed 2026-08-06

- **a third lock file nobody audited** — `apps/api/requirements.lock` sat beside the
  runtime and dev locks carrying **56 known advisories**, no hashes at all, and pins
  eight packages behind the runtime lock: `cryptography==46.0.4` (the exact CVE set
  already found and fixed here to 50.0.0), `pypdf==5.9.0` with 44 advisories — the
  parser that reads uploaded documents — `starlette==0.50.0`, `python-multipart==0.0.29`.

  Nothing installed from it, which is why it survived. Every gate enumerated the two
  files it already knew about: `LOCK_FILES` was a two-item tuple, `python:audit` named
  one path, and `EVIDENCE_SOURCE_PATHS` listed the file — so being inside the provenance
  digest made it *look* governed while no check ever opened it. It is also the most
  obviously-named of the three: `pip install -r apps/api/requirements.lock` is one
  keystroke, and it would have installed unhashed and unpatched.

  The file is deleted. `LOCK_FILES` is now discovered by glob rather than enumerated, so
  a fourth lock is inside the hash gate the moment it exists, and a parity test asserts
  every `requirements*.lock` appears in `python:audit`. Probed: adding
  `requirements.legacy.lock` fails the audit-coverage test; adding an unhashed pin fails
  the hash test.
- **the dev lock had never been audited by anything** — `python:audit` read
  `requirements.runtime.lock` alone. The dev lock is what CI installs, on a runner
  holding a checkout of this repository, so a compromised test dependency reads the tree
  and holds the pipeline's credentials: a strictly larger blast radius than a runtime
  package inside a read-only container. Running pip-audit against it for the first time
  found **PYSEC-2026-1845** in pytest 9.0.2 — a predictable `/tmp/pytest-of-{user}`
  path allowing local denial of service or privilege escalation. Pinned to 9.0.3 with
  its hash. An offline regression test refuses any lock that goes back below a version
  this repository has already answered for, because the security stage runs four stages
  later and, for this file, did not run at all.
- **unfixed container CVEs became invisible rather than absent** — `container:scan`
  passes `--ignore-unfixed`, which is the right gate: refusing to ship over a CVE with
  no patch blocks forever on somebody else's release schedule. But it makes "no
  findings" mean two different things. Measured 2026-08-06: **0 fixable and 24 unfixed**
  HIGH/CRITICAL in `python:3.12.13-slim-bookworm`, 0 and 0 in `nginx:1.31.3-alpine`. The
  job now writes the full severity report as an artefact. Recorded, not enforced — a
  number nobody writes down is a number nobody notices becoming fixable.

### Closed 2026-08-05

A register that still lists closed work is a register nobody can act on, so entries
leave this list only with the mechanism that keeps them closed.

- **hash-locked dependency artifacts** — both lock files carry sha256 for all 68
  artifacts and every install site passes `--require-hashes` (Makefile, two CI steps,
  the API Dockerfile). Two tests hold it: one that every pin carries a hash, one that
  every install enforces them, since pip ignores `--hash` lines without the flag.
- **broad exception handlers in critical paths** — reading all fourteen showed they
  already re-raise, degrade or record. What was missing was anything holding the next
  one to it. `test_exception_handling_discipline.py` refuses a handler that returns a
  value indistinguishable from success, a bare `except:`, or an empty body; probed
  against five swallow shapes.
- **executable retention/deletion/legal-hold scheduler and reconciliation** —
  `application/retention.py` computes a disposition per document (HELD, RETAINED,
  ELIGIBLE, AWAITING_DECISION, UNGOVERNED) and `scripts/plan_retention.py` writes the
  plan and reconciles it against storage. It deletes nothing and is not a timer: in a
  corpus that answers "which order was in force on date X", automatic deletion would
  be data loss driven by a config field. `AWAITING_DECISION` exists because keeping
  expired material quietly reports a clean posture over something nobody ruled on.
  Mutants M121–M123 cover legal hold outranking the timer, deletion without
  permission, and an ungoverned corpus being treated as governed.
- **SIEM export** — `application/audit_export.py` builds resumable, gap-evident
  batches and `scripts/export_audit.py` writes JSON Lines with a manifest and a
  cursor. It refuses to ship a batch whose sequences jump or whose hash links do not
  join: a collector cannot detect a missing event by itself, so a gap shipped quietly
  becomes a clean audit trail over a hole. Payloads stay behind by default — they
  quote corpus material and a SIEM is routinely a lower-classification system — and
  the digest travels instead. The manifest states what an HMAC link does *not* prove:
  a collector cannot detect rewriting by whoever holds the key; that remains the
  external anchor's job. Mutants M124–M126. Correlation into a specific SIEM product
  remains external, like every other integration with a system nobody here operates.
- **dependency license inventory** — read from installed distribution metadata:
  68 of 68 components now carry a declared license where all 68 read UNKNOWN. Legal
  review stays open and is listed above, because a publisher's declaration is not
  clearance for this delivery. The generator exits non-zero when a pinned package is
  absent from the environment, since running it under a bare interpreter resolved five
  of sixty-eight and reported the rest as unknown — a number describing the invocation
  rather than the supply chain. A parity test keeps it on the locked interpreter.
- **number and unit evaluation** — `application/numeric_integrity.py`. Every existing
  extraction predicate fires on visibly broken text; the failure that changes what an
  order *says* leaves the text clean. "не менше 300 м" read as "не менше 3 00 м" has a
  fine alphanumeric ratio, no replacement characters and no long tokens: quotable,
  citable, and wrong by two orders of magnitude. Five forms are detected — a number
  split by a space, a Cyrillic letter standing in for a digit, two decimal separators
  in one passage, a unit pushed past a line break, an inverted range — and each is
  paired with an ordinary passage that must *not* fire, because a flag a reviewer sees
  everywhere is a flag nobody reads. They join `extraction_quality_flags`, which
  already blocks a review transition until acknowledged, so the detection changes a
  decision rather than filling a field. Mutants M127–M128. Table and formula structure
  remain open above.
- **embedding drift monitoring** — `application/embedding_coverage.py`. Retrieval
  filters vectors by the active model id, so a model change yields no semantic
  candidates rather than wrong ones, and the lexical half answers alone from a
  narrower set than the calibrated profile assumed. Four states are distinguished
  because the operator's next move differs: COMPLETE, BACKFILL_REQUIRED,
  MODEL_MIGRATION_REQUIRED and STALE_VECTORS — stale ranked above missing, since
  missing produces silence and stale produces confidence about text the document no
  longer contains. An empty corpus reports 0.0 coverage, not 1.0. Required-semantic
  mode refuses an incomplete index instead of degrading. Mutants M129–M131.
- **live telemetry health probe** — `Observability.telemetry_status()` distinguishes
  DISABLED from REQUESTED_NOT_ACTIVE. The exporter is attached only while the global
  tracer provider is still the proxy, so a configured `otlp_endpoint` can be ignored,
  and until now nothing told an operator reading that config that no span reaches the
  collector. Reported, not enforced: the release policy allows telemetry display to
  degrade while the underlying event stays durably available, and the audit chain is
  not the tracer. `/ready` carries the status word only — it is unauthenticated, and
  the collector address is internal.
- **accessibility validation** — `apps/web/scripts/validate.mjs` now asserts the
  properties a keyboard or screen-reader user depends on: exactly one h1, no skipped
  heading level, an accessible name on every button, a bound label on every control,
  alt on every image, a skip link, a main landmark, and a live region on the panel that
  script fills after an answer arrives. Seven negative controls, one per rule. The web
  shell failed four of them when the rules were first run — the interface had been
  fully verified for what it must not leak and not at all for whether it could be
  operated. Contrast and focus order need a rendered page and stay open above.
- **security configuration validator** — the thirty conditions a controlled deployment
  must satisfy moved out of `Settings.validate_security_and_calibration` into
  `korpus/controlled_requirements.py` as a declared list. Measured complexity of that
  method fell from 103 to 57.

  The number is not the benefit. The benefit is that the conditions are now a document
  that reads start to finish — for an engineer, for the §2.5 assessor, for whoever
  signs the authorisation — instead of control flow to be traced, and the list sits at
  the same granularity as the tests that weaken it one entry at a time. Order is
  preserved exactly, because a configuration violating several conditions reports the
  first, and the 43 tests pinning those messages were written before the move: they
  passed unchanged, which is what makes the refactor evidence rather than hope.

  Growth is now ratcheted. `scripts/check_module_budget.py` records today's line count
  and worst-function complexity for all 94 modules; shrinking is free, growth fails,
  and a new module without a recorded ceiling fails too — "not yet budgeted" is how a
  file reaches two thousand lines unnoticed. Three negative controls. Decomposing the
  repository itself stays open above, with its measurement written down.
- **kubernetes validator** — the fourth and last of the inline validators became a
  register. `manifest_violations` was twenty checks in one function, and the length was
  the least of it: a failure said "korpus-api: root filesystem must be read-only" with
  nothing connecting that sentence to a rule an assessor can cite or an owner can mark
  accepted-with-risk, and a mutant could reach the function but not one check inside it.
  `korpus/kubernetes_requirements.py` generates per-workload and per-container
  requirements from the rendered document set, so an id names one container of one
  workload — `k8s.workload.korpus-api.container.0.read_only_root`. A requirement now
  carries two sentences: `statement` is positive, because a register is read start to
  finish and a list of negations is read wrong under pressure; `failure` is what the
  operator is told, verbatim from the inline version, and it can name what was actually
  found.

  The first draft restated REQUIRED_KINDS instead of importing it, and named five kinds
  where the deployment names nine while dropping seven of the eleven required config
  keys. A register that gates a smaller set than the deployment needs reads exactly like
  one that gates the right set. The constants stay in `application/deployment.py` and
  are imported.

  Thirty-one deployment tests passed unchanged, which is what makes this a refactor
  rather than a rewrite with the tests adjusted to fit. M70 and M71 moved with their
  targets; M134–M137 are new, and M137 survived its first probe — the test counted the
  config requirements and asserted the base deployment passes, and a register can name
  every key while asserting nothing about their values. The register is now part of
  `REQUIREMENTS_REGISTER.md`: 319 requirements where there were 258.
- **infrastructure validator, and one register for every requirement** —
  `validate_infrastructure.main` held about a hundred checks inline and measured a
  cyclomatic complexity of 102. It is now 5: the checks live in
  `korpus/infrastructure_requirements.py` as data, and `application/requirements.py`
  applies them.

  The number was the symptom. Three things were missing and none of them is about
  complexity. A failure had no name — only the sentence appended where it happened —
  so it could not be cited in an audit, marked accepted-with-risk by an owner, matched
  to a mutant, or counted. A mutant could not reach one check among a hundred in one
  function, leaving ninety-nine individually unfalsified. And the requirements could
  not be read: §2.5 asks an outside assessor to judge this system, and the first thing
  they need is the list of properties it claims, not a program that emits that list
  while running.

  157 requirements now carry ids, positive statements and their reasons, exported to
  `REQUIREMENTS_REGISTER.md` and regenerated in `validate`, so a requirement added
  without regenerating fails the gate instead of leaving the document one behind.
  Behaviour is unchanged and the messages are preserved: `test_infrastructure_
  hardening.py` passed untouched, which is what makes a refactor of a security
  validator evidence rather than hope. Mutants M143–M145; M145 survived its first
  probe, because asserting "the register has no duplicate ids" is satisfied by a
  detector that always returns none.
- **table evaluation** — `application/table_integrity.py`. Norms live in tables, and
  PDF extraction has no notion of a cell. The failure is not that a flattened table
  looks broken: a row that loses a column shifts its figures left, so a value is quoted
  under another column's heading. The passage stays grammatical, the citation resolves
  to real bytes, and the answer states a norm that does not exist. Neither the
  character predicates nor `numeric_integrity` can see it — a correct number in the
  wrong column is a correct number.

  Blocks of table-like rows that disagree about their own column count are flagged, and
  the flag joins the same review gate. The first version of the module had the
  membership rule backwards: a row needed three columns to belong to a block, so the row
  that *lost* one broke the block instead of making it ragged, and every damaged table
  read as clean. Nine paired tests — each damage case beside an ordinary passage that
  must not fire — plus mutants M132–M134. Recovering the original cell structure, as
  opposed to detecting its loss, needs layout-aware extraction and stays open above.

The machine-readable source of truth is `docs/audit/closure/KORPUS_v5_FINDINGS_CLOSURE.json`.
