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
Fresh public GitHub PR metadata must name canonical head and base repositories,
the API head must equal the PR head, and the actual checkout must equal the PR
merge commit. Authenticated Git commit metadata must contain exactly the ordered
base/head parents and the locally captured tree. The reusable assurance workflow
reference must identify that same merge commit and PR ref. Stacked PR bases are
supported through their exact base commit, without assuming their branch is main.

The separate `hosted-evidence` workflow uses only `contents: read` and
`actions: read`. It waits at most one hour for this exact independent CI execution
to finish, with finite polling and network budgets. CI does not depend on this
readback workflow. There is no `workflow_run` handoff or in-progress admission.
Public PR metadata is fetched without a token; Actions metadata and downloads use
the read-only token. Credentials are confined to `api.github.com` and never sent
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

Both native coverage datasets require their original execution receipts, exact
run/checkout/source/configuration identity, the locked coverage.py version, and
matching data/report hashes. Native data is regenerated against a private export
of captured Git bytes, then combined independently. A coherent forged report,
a conflicting secondary PostgreSQL copy, or a changed publisher union is refused.
Temporarily replacing caller source and restoring it before final checks cannot
change the admitted statement or branch universe.

Source security requires the exact seven-member artifact: the execution receipt,
native Syft tree SBOM, deterministic lock SBOM, native Gitleaks output, runtime
and combined development pip-audit outputs, and native Trivy output. All five
execution records must succeed and bind the same run and source. Shared producer
validators check exact pinned tool identity, lock census, and native findings;
Syft and Trivy timestamps must fall inside their admitted execution windows.
The scanners' outputs and the SBOM cannot be omitted for a coverage-only PASS.

The fixed `PACKAGE` selector derives its five-member census from captured
`apps/api/src/korpus/release.json`: `dist/<distribution_artifact>`, its `.sha256`
sidecar, and the three `var/package-*-verification.json` / `package-envelope.json`
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
