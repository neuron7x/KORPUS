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
bounded. `make pilot-acceptance ARGS='...'` is an equivalent entry point.

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
