# Live GitHub evidence admission

Issue #102 supplies the positive hosted-evidence path required by #66. A saved
receipt, a local coverage report, and environment variables are not admission
authority. The consumer performs fresh HTTPS reads, captures original artifact
bytes once, and independently reconstructs the native coverage result.

## Fixed identity and execution

The policy admits `neuron7x/KORPUS`, repository ID `1332311807`, owner ID
`206596321`, and CI workflow ID `332983285` at `.github/workflows/ci.yml`.
It requires the latest selected attempt and its exact attempt response to be
completed and successful. Required jobs must themselves be successful GitHub
hosted Ubuntu 24.04 jobs with the expected successful upload step.

For `refs/heads/main`, the event is `push` and the API head equals the actual
clean committed checkout. For `refs/pull/N/merge`, the event is `pull_request`.
Authenticated GitHub PR metadata must name canonical head and base repositories,
the API head must equal the PR head, and the actual checkout must equal the PR
merge commit. Authenticated Git commit metadata must contain exactly the ordered
current-base/head parents and the locally captured tree. The reusable assurance workflow
reference must identify that same merge commit and PR ref. Stacked PR bases are
supported through their exact current base commit, without assuming their branch is main.

### Current base authority and recorded ancestry

The PR response's `base.sha` is a recorded anchor; it is not used as the current
target-branch authority. During the PR #116 integration, fresh authenticated PR
responses retained an older base while GitHub's merge commit already used the
advanced `main` tip. The admission path therefore resolves the PR's exact
`base.ref` through the fixed repository's
[Get a reference endpoint](https://docs.github.com/en/rest/git/refs#get-a-reference).
The returned ref must be exactly `refs/heads/<base.ref>`, its object type must be
`commit`, and its SHA must be a full lowercase commit identity. The checkout's two
ordered parents must equal this current base SHA followed by the exact PR head SHA.
An old merge or a matching tree alone cannot satisfy that equality.

If the recorded and current base SHAs differ, an authenticated
[Compare two commits request](https://docs.github.com/en/rest/commits/commits#compare-two-commits)
must prove a forward ancestry relationship. Its response URL must identify the exact
requested SHA pair, both the base and merge-base identities must equal the recorded
anchor, and its status must be `ahead`. Counts must be integers: `behind_by` must
be zero, `ahead_by` positive, and `total_commits` equal to `ahead_by`. Missing,
divergent, malformed or repointed ancestry is refused. Equal SHAs already establish
the reflexive ancestry case and do not require a comparison request.

The comparison uses `per_page=1&page=2`. GitHub documents that changed-file payloads
appear only on the first comparison page; the ancestry summary is used without
claiming a complete commit census. The transport permits exactly the full-SHA
comparison route and these fixed pagination parameters. The comparison delimiter
does not permit arbitrary traversal, encoded-dot routes or additional query fields.
Both reference and comparison reads use the existing `contents: read` permission.

After the job census and before artifact inventory or downloads, admission re-reads
the PR and current base reference. PR number, merge SHA, both repository and owner
identities, head SHA/ref, base ref, recorded base SHA and current base SHA must all
remain unchanged. This is a bounded observation during `admit_run`; it is not an
atomic GitHub snapshot and does not claim to detect branch movement during later
artifact downloads or coverage reconstruction. A changed or unavailable subject
refuses admission instead of falling back to the recorded base.

The separate `hosted-evidence` workflow uses only `contents: read` and
`actions: read`. It waits at most one hour for this exact independent CI execution
to finish, with finite polling and network budgets. CI does not depend on this
readback workflow. There is no `workflow_run` handoff or in-progress admission.
PR metadata, Actions metadata, and API download requests use the existing
read-only token. Credentials are confined to `api.github.com` and never sent
to the restricted HTTPS artifact-storage redirect allowlist.

## Captured artifact contracts

| Subject | Successful producer job | Artifact prefix | Upload step |
| --- | --- | --- | --- |
| SQLite native coverage | `api-tests` | `api-coverage-diagnostics` | `Preserve API and coverage diagnostics` |
| PostgreSQL native coverage | `assurance / postgres-full-suite` | `coverage-postgres` | `Upload PostgreSQL coverage evidence` |
| Source SBOM and scanners | `source-security` | `source-security-evidence` | `Upload source security evidence` |
| Canonical source package | `canonical-package` | `canonical-package` | `Upload verified source package` |

Artifact names end in the selected run attempt. GitHub metadata, upload-step
timestamps, and the authenticated log of the pinned upload action must agree on
artifact ID and SHA256. The downloaded outer ZIP must match that digest and size.
Existing ZIP safety limits run before any member is consumed. Metadata responses
are limited to 2 MiB, native JSON and logs to 16 MiB, outer ZIPs to 64 MiB, and
each admission transport to 32 requests. Collections must be complete within the
100-item bound. Ambiguous JSON and ZIP paths are rejected.

### Upload invocation boundaries

The producer job API reports whole-second step timestamps, while its log carries
fractional timestamps. The existing inclusive-start/exclusive-end window remains
`[started_at, completed_at + 1 second)`. Adjacent serial uploads can legitimately
start in the same final second, so a unique action header across that entire
window is not a valid identity predicate.

The importer partitions the authenticated job log at every runner
`##[group]Run ...` header, including foreign actions and shell commands. It selects
exactly one invocation containing the expected artifact name and ID finalization.
That invocation must contain the exact pinned upload action, expected SHA256 and
expected finalization exactly once, in that order, with every selected event
inside the original upload-step window. Duplicate selected finalizations and
evidence split across invocations refuse admission. An adjacent artifact can
have the same ZIP digest without owning the selected artifact ID.

The runner's `##[endgroup]` closes its input/environment metadata before executing
the action; it is not the upload invocation's end. This follows the pinned
[runner metadata implementation](https://github.com/actions/runner/blob/d1eb12d4b115c301201de27d667284e1a80f2ab5/src/Runner.Worker/Handlers/Handler.cs)
and [handler execution order](https://github.com/actions/runner/blob/d1eb12d4b115c301201de27d667284e1a80f2ab5/src/Runner.Worker/ActionRunner.cs).
The boundary applies to the current serial producer steps in the authenticated
CI workflows, not arbitrary background-step interleaving. The immutable
[upload action](https://github.com/actions/upload-artifact/blob/cf430e030ddbb5b0abf93d22962f4752f3646cd9/src/shared/upload-artifact.ts),
successful producer/step requirements, artifact metadata, archive digest/size
checks, permissions and network budgets are unchanged.

The regression excerpts come from
[CI run 44616015657](https://github.com/neuron7x/KORPUS/actions/runs/44616015657).
Its API upload passed the old binding predicate, while PostgreSQL, source-security
and package upload windows each contained two pinned headers and one exact
digest/finalization pair. For example, PostgreSQL finalized artifact `14576640600`
at `21:21:10.0156215Z`; the next diagnostics upload began at `21:21:10.0404529Z`,
inside the same rounded step window. The old predicate rejected all three;
the new tests replay their exact relevant log lines and retain the API control.
These saved excerpts establish parser regression behavior. They are not a live
admission input or a successful hosted readback for the repaired revision.

For a PR with an advanced base and all four producers, the normal single storage
redirect per download consumes 26 requests:

| Read category | Requests |
| --- | ---: |
| Latest run and selected attempt | 2 |
| Exact checkout commit | 1 |
| Initial and final PR subjects | 2 |
| Initial and final current base references | 2 |
| Recorded-to-current base comparison | 1 |
| Job census and artifact inventory | 2 |
| Four artifact ZIPs and four upload logs, each API GET plus one storage GET | 16 |
| Total | 26 |

The 32-request limit remains a hard refusal. Extra storage hops consume the same
budget; all eight downloads taking two storage hops would require 34 requests and
are refused. Tests execute both cases through the real transport with a controlled
HTTPS response boundary, preserving authentication and byte limits.

Both native coverage datasets require their original execution receipts, exact
run/checkout/source/configuration identity, the locked coverage.py version, and
matching data/report hashes. Native data is regenerated against a private export
of captured Git bytes, then combined independently. A coherent forged report,
a conflicting secondary PostgreSQL copy, or a changed publisher union is refused.
Temporarily replacing caller source and restoring it before final checks cannot
change the admitted statement or branch universe.

Source security requires the exact eight-member v2 artifact: the execution receipt,
native Syft tree SBOM, deterministic lock SBOM, native Gitleaks output and original log, runtime
and combined development pip-audit outputs, and native Trivy output. All five
execution records must succeed and bind the same run and source. Shared producer
validators check exact pinned tool identity, lock census, and native findings;
Syft and Trivy timestamps must fall inside their admitted execution windows.
The scanners' outputs and the SBOM cannot be omitted for a coverage-only PASS.
The original log bytes are included in the receipt's member hashes and independently
revalidated after authenticated ZIP capture. Explicit Gitleaks input/error/partial
diagnostics refuse admission even with exit zero and empty JSON. Missing-log and
v1 artifacts are refused without consulting a diagnostics archive. Required
terminal log framing detects incomplete summaries; it does not prove Git input
EOF. This adds no API request or alternative scanner authority.

The fixed `PACKAGE` selector derives its five-member census from captured
`apps/api/src/korpus/release.json`: `dist/<distribution_artifact>`, its `.sha256`
sidecar, and the three generated outputs `var/package-first-verification.json`,
`var/package-second-verification.json`, and `var/package-envelope.json`
reports named by the producer. Missing, foreign, or extra members are refused.
This transport boundary captures the package without substituting report verdicts
for package semantic verification; that consumer belongs to #104.

## Reusable immutable boundary

`fetch_with_artifacts(root, selection, extra_producers)` performs one source,
run, inventory, and transport capture. It returns immutable native `HostedEvidence`
and ordered immutable `CapturedArtifact` extras. `PACKAGE` is resolved internally;
there is no arbitrary artifact-selector CLI. The cryptographic adapter can request
the fixed package and provenance producers together, without a second admission.

`HostedEvidence.identity` preserves API head separately from actual checkout
commit/tree, exact run/attempt, and the existing evidence, coverage, tracked-tree,
and mode-aware tracked-tree digest scopes. `source_members` exposes immutable
captured source and identity bytes. `source_identity_members` is the separate
fixed census of `SOURCE_MANIFEST.json`, `PACKAGE_BUILD.json`, and the release
identity. These files are captured from exact committed Git blobs and compared
with working bytes and modes; generated identity files do not enter the existing
source digest denominators. Each artifact preserves its original outer ZIP bytes and
immutable member bytes. Metadata diagnostics are fresh copies; modifying them
does not modify admitted authority. Package consumers can compare source manifest,
build identity, and release identity bytes without reopening caller paths or
equating different digest scopes.

## Commands and scope

```sh
python scripts/import_github_evidence.py --run-id RUN_ID --run-attempt ATTEMPT \
  --ref refs/heads/main --out var/hosted-evidence
python scripts/await_github_evidence.py --ref refs/pull/NUMBER/merge \
  --out var/hosted-evidence
```

The release publisher requests fresh admission only when all three explicit
selectors are set: `KORPUS_EVIDENCE_RUN_ID`, `KORPUS_EVIDENCE_RUN_ATTEMPT`, and
`KORPUS_EVIDENCE_REF`. It checks the captured source digest and captured release
identity before publishing a coverage projection. Raw local coverage remains
inadmissible. The CLI revokes stale PASS receipts before an attempted readback.

This implementation establishes live GitHub transport and source correspondence.
It reports `signature_verified: false` and `production_authorized: false`.
Sigstore verification belongs to #103, and production authorization remains a
separate decision. Unit fixtures exercise real native coverage bytes and explicit
test transports; they do not stand in for a successful live hosted round trip.


## Authenticated PR discovery

The readback uses the existing workflow token for the single-PR metadata request
as well as Actions metadata. GitHub documents `contents: read` as a sufficient
permission for [Get a pull request](https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request),
so the workflow's existing read-only permissions are unchanged. Credentials are
sent only to the fixed GitHub API host and never to artifact storage redirects.

[Readback run 44607373043](https://github.com/neuron7x/KORPUS/actions/runs/44607373043)
on head `ae602e01` failed during initial readback with HTTP 403. Separately, code
inspection confirmed that the prior transport suppressed its token for PR
metadata. The saved diagnostic identified neither the refused endpoint nor the
server's reason, so an anonymous rate-limit cause is not established.
GitHub's [unauthenticated quota](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
is associated with the requesting IP; authenticated discovery avoids relying on
that shared anonymous quota while preserving the existing permission boundary.

A refused response still fails admission. There is no anonymous retry or saved
receipt fallback. Diagnostics now identify the relative API endpoint and HTTP
status without emitting tokens or response bodies. Tests cover 401, 403 and 429,
authenticated PR metadata, and token exclusion from storage redirects; M764 guards
against reintroducing silent PR-token suppression. A successful native readback
on the corrected head is required before hosted evidence can be accepted.
