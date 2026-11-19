# Source security execution evidence

The `source-security` job in `.github/workflows/ci.yml` executes the existing
source scanner set and records native outputs for the current GitHub Actions
run and attempt. A receipt is evidence within that job's authenticated execution
boundary. It is not a production authorization, deployment attestation, container
image SBOM, or a claim that no undiscovered vulnerabilities exist.

## Source and tool boundaries

The producer requires the checkout HEAD to equal `GITHUB_SHA`. For a pull request
this is the checked-out synthetic merge commit, not necessarily the PR head.
It admits the exact regular-file source inventory with the existing Git tree
validator, preserving executable modes. It exports those verified bytes into a
fresh directory under `RUNNER_TEMP`, outside the repository. The coverage source
snapshot must agree with that export. Full Git source admission, checkout/tree
identity, snapshot hashes, and the exported inventory are checked again after
the commands finish.

Gitleaks examines the exact commit's reachable history in the read-only checkout
with the existing committed baseline and redaction enabled. Syft and Trivy see
only the read-only exported source. The pip-audit environment and fresh HTTP
caches are outside source; the audit reads the exported locks. Generated
reports, `.git`, and local environments are excluded according to the canonical
source inventory predicate. No production corpus or credentials are inputs.

The images are the immutable digests already declared for the archived canonical
source jobs: Gitleaks 8.30.1, Trivy 0.70.0, and Syft 1.44.0. The independent
pip-audit 2.10.1 environment is completely pinned by
`apps/api/requirements.scanners.lock`, including transitive binary distributions
for CPython 3.12 on Linux x86_64. Installation requires hashes and disables
dependency resolution. The lock is not part of the application's runtime/dev
dependency universe. Updating it requires review of the actual new wheel bytes.
Before the five source executions, a separate fatal preflight audits every
scanner-toolchain pin against live PyPI advisories and validates the exact native
package census. Its JSON is preserved in `source-security-toolchain-${run_attempt}`;
it does not replace an application audit or enter the seven-member source artifact.

Pip-audit queries the live PyPI vulnerability service using a new per-command
cache; the receipt records the command and its actual start/end time. This is a
time-specific advisory observation. Trivy uses the rules bundled in its pinned
image (`--skip-check-update`) and the existing HIGH/CRITICAL policy with the
existing path-scoped, expiring ignore file. That flag pins policy code; it does
not skip scanning. No ignore entry or severity is relaxed by this producer.

Each pinned container image is pulled before native scanning, with its own
240-second bound, start/end timestamps and exact exit code in `provisioning`.
All three pulls must succeed. The scanner then uses `--pull=never`. Gitleaks has
a separate 930-second parent bound; other scanner calls retain 240 seconds.
Pull logs are retained alongside the
native diagnostics. The job's 25-minute outer bound, immutable image digests,
offline scanner containers, and complete reachable-history scope are unchanged.

## Native reports and receipt

The artifact `source-security-evidence-${run_attempt}` has exactly seven members.
These are generated at the paths below; the upload stores each basename at the
artifact root:

| Generated output path | Meaning |
| --- | --- |
| `var/source-security/source-security-receipt.json` | Run/repository/attempt, checkout commit/tree, before/after source binding, tool identities, five real execution outcomes, and hashes of the other six members |
| `var/source-security/gitleaks.json` | Native redacted findings array; admitted only when empty |
| `var/source-security/pip-audit-runtime.json` | Native audit of every runtime lock pin; no skipped dependency, vulnerability, or repair |
| `var/source-security/pip-audit-dev.json` | Native audit of the exact union of runtime and development pins |
| `var/source-security/trivy.json` | Native configuration results with a positive census of passing HIGH/CRITICAL rules and no unaccepted failure |
| `var/source-security/tree-sbom.cdx.json` | Actual Syft directory discovery in CycloneDX 1.6, including native tool/source metadata |
| `var/source-security/lock-sbom.cdx.json` | Deterministic complete application lock component universe in CycloneDX 1.6 |

The development command explicitly names both lock files. With `--disable-pip`,
pip-audit 2.10.1 does not traverse the development lock's nested `-r` directive;
auditing that file alone would silently omit runtime dependencies. The shared
validator derives the expected package census from the exact current locks,
rather than storing a package count as a success criterion.

Syft's discovery ability is distinct from lock completeness. The tree report is
not substituted with the deterministic lock SBOM, and a tree cataloger missing
a lock format does not make the complete lock universe disappear. The shared
consumer validates native CycloneDX tool/source structure and validates the lock
SBOM against the exact deterministic component universe. It does not falsely
claim that Syft found every Python lock component.
The lock SBOM uses RFC 4122 UUID5 serial numbers. Its runtime components use
CycloneDX `required` scope and development-only components use `excluded` scope,
the standard's scope for test and other non-runtime usage. Runtime membership
takes precedence if a package appears in both locks; `development` is not a
valid CycloneDX 1.6 scope value.

`scripts/source_security_contract.py` exports `validate_outputs(members, root)`
and `expected_tools(root)` for the producer and authenticated importer. Native
JSON must reject duplicate keys and nonfinite values. Receipt schema is
`korpus.source-security-execution.v1`; `production_authorized` is always `false`.
The receipt itself is not its own authority: consumers must authenticate the
workflow, run attempt, successful job/upload step, checkout tree and downloaded
artifact bytes through their separate hosted-evidence boundary.

## Failure behavior and proof limits

After image provisioning succeeds, every scanner is attempted even when an
earlier scanner fails. The producer
writes PASS only after all five exact integer exit codes are zero, all six
native outputs satisfy their semantics, and source remains unchanged. An absent
scanner, timeout, stale output directory, malformed output, partial package
census, or source mutation refuses admission. Native JSON and redacted logs are
retained in separate evidence/diagnostic artifacts; failed jobs cannot become
positive evidence through the `always()` upload step.

The unit suite uses explicitly neutral native-format fixtures to falsify
admission boundaries. These tests do not prove that hosted scanners executed.
That final positive requires the actual job and its immutable artifacts. No
`LOCAL_SCANNERS` result is promoted into this hosted class.

## Measured first hosted failure and bounded repair

[CI run 44585835735](https://github.com/neuron7x/KORPUS/actions/runs/44585835735),
attempt 1, failed source security on checkout
`c2267bb0f2ecd7e98c6784ae2354a707fafe2560` on 2026-11-19. The native Gitleaks
command timed out after 240 seconds without its JSON report. Its log contains
image download progress and the timeout, but no timestamped separation of pull
and scan. The share of time spent in either phase is **inconclusive**. The new
separate provisioning records make that distinction measurable; they do not
establish that the next full-history scan will finish.

Both application dependency audits and Syft completed successfully. Trivy
returned two HIGH findings, retained in the original native report:

- KSV-0109 classified the public OIDC token endpoint by its ConfigMap key name.
  The public URL now has the explicit `PUBLIC_OIDC_EXCHANGE_URL` key. Every API,
  worker and migration container maps it through `configMapKeyRef` to the
  existing `KORPUS_OIDC_TOKEN_ENDPOINT` runtime variable. Credentials remain in
  Secrets. Both rendered deployment variants are tested. The expired ignore
  entry is not renewed or broadened.
- GCP-0015 reported the existing `ENCRYPTED_ONLY` Cloud SQL setting. That mode
  already enforces TLS; the finding is not proof of plaintext transport.
  [Google's TLS configuration contract](https://docs.cloud.google.com/sql/docs/postgres/configure-ssl-instance),
  [Aqua's current GCP-0015 reference](https://avd.aquasec.com/misconfig/google/sql/gcp-0015/)
  and [the upstream false-positive report](https://github.com/aquasecurity/trivy/issues/9999)
  distinguish it from permitting unencrypted connections. The configuration is
  hardened to `TRUSTED_CLIENT_CERTIFICATE_REQUIRED`, which also verifies client
  certificates. Required Cloud SQL connectors and private-only networking remain
  enforced. The production contract rejects either a TLS or client-certificate
  downgrade. No infrastructure was applied by this source change.

The downloaded ZIP bytes matched these GitHub artifact API SHA256 digests:

| Artifact ID | Native artifact | SHA256 |
| --- | --- | --- |
| 14559089806 | source-security-evidence-1 | `188bf557e6fe479c7bdbd6f18100bef5786f664f9c1ed040b8df974fb30985c0` |
| 14559049885 | source-security-diagnostics-1 | `e282aa55d1c44a65356b77a9c03312de7badb32fa19160076e44ff15c10dcdd9` |
| 14561587649 | source-security-toolchain-1 | `e19f8cd7aae566e689b6eef91337f9936cd96bcc6b3520901d34be3a3a072d36` |

This failed run remains diagnostic evidence. A new successful canonical run,
matching the current PR merge checkout, and authenticated read-back are required
before these changes can support a hosted-evidence success claim.

Upstream format and command references used for this contract:

- [pip-audit 2.10.1 native JSON formatter](https://github.com/pypa/pip-audit/blob/v2.10.1/pip_audit/_format/json.py)
- [Syft 1.44.0 CycloneDX metadata](https://github.com/anchore/syft/blob/v1.44.0/syft/format/common/cyclonedxhelpers/to_format_model.go)
- [CycloneDX 1.6 schema](https://github.com/CycloneDX/specification/blob/1.6/schema/bom-1.6.schema.json)
- [Trivy 0.70.0 native report](https://github.com/aquasecurity/trivy/blob/v0.70.0/pkg/types/report.go)
- [Trivy result filtering and rule census](https://github.com/aquasecurity/trivy/blob/v0.70.0/pkg/result/filter.go)
- [Gitleaks 8.30.1 native JSON reporter](https://github.com/gitleaks/gitleaks/blob/v8.30.1/report/json.go)
## Timeout ownership and diagnostic boundary

The original producer used a 240-second `subprocess.run` timeout for `docker run --rm`.
That bounds the Docker client process; automatic removal occurs after the container
exits. An independent real POSIX process counterexample, using the exact original
execution function and a shortened test timeout, showed a daemon-like worker writing
to the output directory after its client had been killed. This establishes a cleanup
defect, not the cause of the observed Gitleaks timeout and not a native Docker
reproduction.

Each scanner container now receives a unique name, ownership label, and private CID
file outside the mounted source/output directories. Cleanup queries the exact
identity, checks its full ID and ownership label before forced removal, and requires
a successful independent absence query. Unknown ownership, unavailable daemon,
malformed CID file, missing creation outcome, or a surviving container remains
`UNPROVEN` and cannot produce an admitted successful execution. The producer and
authenticated consumer both enforce this condition. Removal never targets an
unverified container name or an unrelated container inventory.

A zero-byte regular CID file is treated as an incomplete creation response. Cleanup
then resolves the exact generated name and still verifies the full ID and ownership
label before removal. No matching container leaves creation unproven. A nonempty
malformed file, symlink, or nonregular file never becomes removal authority.

Gitleaks receives `--timeout 900` with a 930-second parent bound. Other scanner
calls and image pulls retain 240 seconds; cleanup queries retain 10 seconds.
The pinned v8.30.1
[command context and failure handler](https://github.com/gitleaks/gitleaks/blob/v8.30.1/cmd/root.go)
use a cancellation context and a nonzero exit for scan errors, including partial
scans. A nonzero exit remains a failure even when a native report exists. The actual
full-history scan must still complete successfully in hosted CI.

An earlier qualification run
[44602028545, job 135835685439](https://github.com/neuron7x/KORPUS/actions/runs/44602028545/job/135835685439)
used tree `b01163f098d842c3689768c8128e7f7dc53c75f1`. Its 230-second native deadline
interrupted the history scan after approximately 303.72 MB and 761 commits; the
partial report correctly remained a failed execution. Pulls took about eight
seconds and the four other scanners about 4.3 seconds combined.

Two subsequent native runs used the 600-second allocation:

- [Run 44607373087, job 135854556828](https://github.com/neuron7x/KORPUS/actions/runs/44607373087/job/135854556828)
  on head `ae602e01`, merge `64b52682`, tree
  `3fec84f067b1009e227c8c90535814749b54f19e` completed with exit 0 in approximately
  339 seconds. Gitleaks reported 1296 commits, 544,176,163 scanned bytes and no leaks
  under the configured rules and baseline.
- [Run 44609740798, job 135863006310](https://github.com/neuron7x/KORPUS/actions/runs/44609740798/job/135863006310)
  on head `16bfba03`, merge `59249b2e`, tree
  `527619ad70c19106814236d13c47ac4bd5e9a298` reached the 600-second native deadline
  and exited 1 after 600.521 seconds. Its partial scan reported 1114 commits and
  501,815,047 scanned bytes. Zero findings in that partial report did not qualify
  as a completed clean scan. Pulls took approximately 7.36 seconds combined, and
  the four other scanners exited 0. All three container receipts confirmed absence
  after natural removal; forced cleanup after a parent timeout was not exercised.

The observed scan durations differ; these measurements do not establish the cause.
The 900-second allocation adds bounded headroom above the failed native deadline,
with a 30-second parent margin. It is a further qualification attempt, not a proven
performance fix or evidence that this revision completes the full history. The
earlier complete result applies only to its own head and checkout. CPU and memory
limits, isolation, pins, history scope, rules, redaction, strict exit predicates and
cleanup requirements remain unchanged.

`--log-level info` preserves completion/error summaries while avoiding the
per-decoded-segment debug stream. It changes no history, rules, decoding, pins,
redaction, dependency scope or output acceptance predicate.

The existing 25-minute job limit is an outer cancellation cap. The sum of all
sequential per-call maxima can exceed it; adverse timing can prevent cleanup
receipts or diagnostic uploads from completing. A cancelled or incomplete job
cannot be admitted. No worst-case completion guarantee is claimed.

Regression tests exercise a modeled Docker daemon with a real worker process,
successful cleanup, unknown ownership, failed queries, missing creation identity,
surviving removal, and coherently rehashed hosted receipts with missing cleanup.
They do not establish native Docker execution in this local environment. Hosted
verification of this revision remains pending; no successful Gitleaks measurement,
complete evidence admission, or production authority is inferred from these tests.

