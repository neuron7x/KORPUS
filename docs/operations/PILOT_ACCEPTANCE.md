# Live pilot acceptance

`scripts/run_pilot_acceptance.py` checks a running KORPUS API with actual bearer
credentials, uploaded source bytes, review transitions, retrieval and exact source
disclosure. It supports synchronous ingestion and durable ingestion with a running
worker. It does not replace authentication, retrieval, answers or the HTTP transport.

## Prepare a disposable scope

Use an isolated test instance or provision a dedicated corpus named
`pilot-smoke-<name>`. Keep real documents out of that corpus. Supply credentials
already issued by the deployment's administrator:

| Identity | Required access |
| --- | --- |
| Owner | Smoke corpus and `document:ingest` |
| Metadata reviewer | Smoke corpus and `document:review_metadata` |
| Content reviewer | Smoke corpus and `document:review` |
| Approver | Smoke corpus and `document:approve` |
| 3–5 distinct readers | Smoke corpus; only `answer:read` and `document:list` |
| Optional outsider | Read permissions; no access to the smoke corpus |

The owner is the default for each review stage. Supply separate review credentials
when the configured separation policy requires them. Readers must differ from the
owner and reviewers. The probe changes no entitlement, signing secret, review
policy, retrieval threshold or runtime setting.

`--exercise-fixture` explicitly authorizes uploading and reviewing **one generated
synthetic document**. Its issuer identifies it as a smoke fixture; its authority is
`analytical`. It never loads or approves operator documents. Source bytes, document
metadata and audit events remain in the test corpus after the run. The report records
their identifiers. No cleanup deletes or rewrites audit evidence. Use a fresh
disposable corpus/instance for each acceptance run; retained earlier fixtures may
affect the quarantine abstention check.

## Run through the intended origin

Put supplied credentials in private files or pre-existing environment variables.
Arguments accept `file:PATH` and `env:NAME` references, never literal bearer values.
Do not put secrets in shell history. For example, with credentials already present
in the named files:

```sh
apps/api/.venv/bin/python scripts/run_pilot_acceptance.py \
  --base-url http://127.0.0.1:8000 \
  --corpus-id pilot-smoke-first \
  --exercise-fixture \
  --owner-credential file:/private/pilot/owner.token \
  --metadata-credential file:/private/pilot/metadata.token \
  --content-credential file:/private/pilot/content.token \
  --approver-credential file:/private/pilot/approver.token \
  --reader-credential file:/private/pilot/reader-1.token \
  --reader-credential file:/private/pilot/reader-2.token \
  --reader-credential file:/private/pilot/reader-3.token \
  --outsider-credential file:/private/pilot/outsider.token \
  --out var/pilot-acceptance.json
```

For the reader-facing edge, use `--base-url https://your-pilot.example/api` so requests
cross the same proxy prefix as the browser. HTTPS is required outside loopback, TLS
verification remains enabled, redirects are not followed, and response sizes are
bounded. The Make entry point names every required input explicitly:

```sh
make pilot-acceptance \
  PILOT_BASE_URL=http://127.0.0.1:3000/api \
  PILOT_CORPUS_ID=pilot-smoke-first \
  PILOT_OWNER_CREDENTIAL=file:/private/pilot/owner.token \
  PILOT_READER_1_CREDENTIAL=file:/private/pilot/reader-1.token \
  PILOT_READER_2_CREDENTIAL=file:/private/pilot/reader-2.token \
  PILOT_READER_3_CREDENTIAL=file:/private/pilot/reader-3.token \
  ARGS='--exercise-fixture --content-credential file:/private/pilot/content.token --approver-credential file:/private/pilot/approver.token'
```

`ARGS` carries optional flags, including a fourth/fifth reader credential, a separate
metadata reviewer, an outsider credential or a report path. Neither entry point
supplies a default identity or authorizes fixture mutation implicitly.

Each request has a configurable total `--timeout` (default 15 seconds, maximum 60),
covering connection, headers and the complete response body. A stream that keeps
sending small chunks cannot extend this deadline.
Durable ingestion has a separate bounded `--job-timeout` (default 60 seconds,
maximum 300). The deployment must already have its worker running; the probe does
not start one or switch ingestion modes. Dead-letter jobs and exhausted deadlines
fail the probe.

## Interpret the result

Exit `0` and report `status: PASS` require all of these checks:

- Server-verified, distinct reader identities and effective read-only permissions.
- Missing/malformed credentials denied, and reader writes denied.
- A fresh uploaded version starts quarantined and cannot answer or disclose spans.
- All three explicit fixture review transitions succeed under the configured policy.
- Every reader gets the fixture fact, with claims bound to citations, exact quote
  offsets and SHA-256 checks over the quote, disclosed span and original upload.
  Disclosed text must also occur in the independently known fixture bytes; matching
  hashes supplied by the server are not sufficient by themselves.
  This narrow fixture checks an extractive answer: its body must join the verified
  claims, and any opening must be an exact excerpt of the fixture. A differently
  worded model composition fails this probe; the probe never changes model settings.
  Positive limitations must be the exact standard extractive/ranking caveats, with
  a repeated-source caveat for repeated citations and an optional fixed composition
  caveat (required when an opening is present).
  Extra prose, missing caveats and an unexpected decision reason fail acceptance.
  Visible source metadata is bound to the known title, revision, section, dates and
  authority of this fixture; its presentation/adjudication fields must match the
  fixture's fixed verdict. The displayed corpus release must be a content hash.
- The same question before the fixture's effective date abstains, with no claims or
  citations; its source spans are unavailable on that date. Both empty-evidence
  checks require the expected `retrieval_gate_failed` refusal text, empty opening
  and standard limitation message, so rendered text cannot leak the fixture while
  an empty citation list pretends to abstain.
- An unassigned corpus is denied. With the optional outsider credential, direct
  source disclosure to that identity is denied too.

Unexpected HTTP statuses, invalid response shapes, timeouts, missing citations and
broken provenance links fail closed. Abstention by itself cannot pass: the approved
positive case must also succeed. Reports contain check identifiers, runtime release,
observed thresholds, hashed reader subjects and synthetic source identifiers; they
omit tokens and raw response bodies.

This report proves the measured **authenticated HTTP journey**. It does not establish
browser/OIDC login usability, Internet reachability from a friend's device, capacity,
restart/backup recovery, quality on the owner's real documents or production approval.
The existing `scripts/gcp/live_smoke.py` measures the HTTPS edge separately;
`scripts/probe_blank_corpus.py` measures a broader question set's temporal ablation.

## Reproduce the regression test

```sh
PYTHONPATH=apps/api/src apps/api/.venv/bin/python -m pytest \
  apps/api/tests/test_pilot_acceptance.py
```

The integration cases launch disposable uvicorn processes with real JWT signatures,
isolated SQLite/object stores, normal admission thresholds and review separation
enabled. The durable case also launches the actual worker loop. They exercise three
readers synchronously and five through durable ingestion. Pure negative cases poison
source hashes, offsets, permission sets and abstention payloads to verify the probe
rejects false successes. A real TCP trickle-response test checks the total deadline.
Neither live case overrides `get_identity` or stubs answers.

## PostgreSQL durable queue boundary

The API and worker must bind each queue transaction through the repository's separate
authorization broker. Migration `0020_rls_identity_boundary` reads that trusted context;
the old `korpus.subject` / `korpus.roles` session settings grant no queue access. Missing
broker wiring now fails at queue construction on PostgreSQL. Application, authorization
and review database identities retain their existing distinct permissions.

Run the native regression against the runner's disposable migrated database:

```sh
scripts/run_postgres_suite.sh --targeted apps/api/tests/test_postgres_ingestion_queue.py
```

It proves app-role enqueue, owner/auditor visibility, worker claim/retry/completion,
wrong-worker refusal and expired-lease reaping, with direct-SQL forged-claim denial.
The fixture refuses reset outside `korpus_suite`, `korpus_coverage` or `korpus_test` and
requires app, owner and broker URLs to address the same database with distinct logins.
Only suite cleanup uses the owner; queue operations never do. Synthetic completion
metadata proves queue persistence. The authenticated live acceptance above still has
to prove actual upload, document processing, review and source-grounded answers.

## PostgreSQL reviewer-only transitions

Migration `0028_reviewer_update_scope` adds two permissive UPDATE policies. Each
requires the trusted broker's `reviewer` role, the original document visibility and
the actual SQL login's existing review-column privilege. API application credentials
do not gain review authority; content reviewers and approvers do not need curator or
administrator roles. The review login's existing table-level version UPDATE grant
remains a capability discriminator, not a new column whitelist. Sealed-provenance
guards and non-review document-column grants continue to apply.

Run the native regression with the disposable PostgreSQL runner:

```sh
scripts/run_postgres_suite.sh --targeted apps/api/tests/test_postgres_reviewer_scope.py
```

It exercises distinct metadata/content/approval identities, including a separately
named review login, and verifies app-role, forged-claim, scope and new-row denials.
An access-tier UPDATE affecting zero rows aborts the entire review transaction,
including predecessor retirement and audit changes.

The new head is eligible for fresh database bootstrap. Existing populated-deployment
retirement admission remains required, including an existing `0027` database; do not
stamp a revision or delete a pilot volume to bypass it. The expand-only assessment
continues to report the 32 existing findings for `0025`–`0027`. The narrowly proven
additive `0028` policies add no findings and do not authorize production deployment.
