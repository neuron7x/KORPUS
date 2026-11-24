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

Gitleaks is configured to traverse the exact commit's full reachable history in
the read-only checkout, including merge patches against their first parent,
with the existing committed baseline and redaction enabled. Completion under
the required time budget still requires native evidence for this revision.
Syft and Trivy see
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
it does not replace an application audit or enter the eight-member source artifact.

Pip-audit queries the live PyPI vulnerability service using a new per-command
cache; the receipt records the command and its actual start/end time. This is a
time-specific advisory observation. Trivy uses the rules bundled in its pinned
image (`--skip-check-update`) and the existing HIGH/CRITICAL policy with the
existing path-scoped, expiring ignore file. That flag pins policy code; it does
not skip scanning. No ignore entry or severity is relaxed by this producer.

Each pinned container image is pulled before native scanning, with its own
240-second bound, start/end timestamps and exact exit code in `provisioning`.
All three pulls must succeed. The scanner then uses `--pull=never`. Every scanner
call retains the original 240-second parent bound; Gitleaks has a 230-second native
deadline. Pull logs are retained alongside the native diagnostics. The job's
25-minute outer bound, immutable image digests, and offline scanner containers
are unchanged. The corrected merge-patch scope is specified below.

## Native reports and receipt

The v2 artifact `source-security-evidence-${run_attempt}` has exactly eight members.
These are generated at the paths below; the upload stores each basename at the
artifact root:

| Generated output path | Meaning |
| --- | --- |
| `var/source-security/source-security-receipt.json` | Run/repository/attempt, checkout commit/tree, before/after source binding, tool identities, five real execution outcomes, and hashes of the other seven members |
| `var/source-security/gitleaks.json` | Native redacted findings array; admitted only when empty |
| var/source-security/gitleaks.log | Exact original native log bytes; explicit input/error/partial diagnostics and incomplete success framing refuse admission |
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
`korpus.source-security-execution.v2`; `production_authorized` is always `false`.
The v2 importer rejects v1 receipts and missing-log artifacts. The log is validated
as native text, while the six original report members retain their strict JSON
semantics. There is no fallback to a separate diagnostics artifact.
The receipt itself is not its own authority: consumers must authenticate the
workflow, run attempt, successful job/upload step, checkout tree and downloaded
artifact bytes through their separate hosted-evidence boundary.

## Failure behavior and proof limits

After image provisioning succeeds, every scanner is attempted even when an
earlier scanner fails. The producer
writes PASS only after all five exact integer exit codes are zero, all seven
native outputs satisfy their semantics, and source remains unchanged. An absent
scanner, timeout, stale output directory, malformed output, partial package
census, or source mutation refuses admission. Native JSON and the original
Gitleaks log are bound in the evidence artifact; the other logs and CPU profile
remain diagnostic outputs. Failed jobs cannot become
positive evidence through the `always()` upload step.

The unit suite uses explicitly neutral native-format fixtures to falsify
admission boundaries. These tests do not prove that hosted scanners executed.
That final positive requires the actual job and its immutable artifacts. No
`LOCAL_SCANNERS` result is promoted into this hosted class.

## Native input errors and the v2 log contract

The [2026-11-20 native diagnostic](https://github.com/neuron7x/KORPUS/actions/runs/44643158063)
found a concrete upstream failure mode. Both engines found a neutral marker in
an intact private fixture, then returned exit zero and an empty findings array
after that fixture's known historical blob was deliberately removed. Independent
Git log and fsck returned 128 and 2; both scanner logs reported the read failure.
The original [native log members](https://github.com/neuron7x/KORPUS/actions/runs/44643158063/artifacts/14587007971)
are preserved as regression bytes with run, artifact and member hashes. This is
not evidence that the canonical repository history is corrupt, or that an
enabled default rule missed a real secret. The separate custom-rule UTF-8
disagreement does not establish either claim.

The shared validator now requires the exact native log in the authoritative
artifact. The producer captures at most 16 MiB from one regular file, refuses
unsafe or changing captures, and hashes and validates those same unmodified
bytes. The hosted importer recomputes that member hash from the original ZIP
and runs the same semantic validation; a rewritten PASS or clean-log boolean
cannot replace the bytes. JSON-encoded log strings are not native logs.

The inspection view removes only complete ANSI color sequences and refuses
unsupported controls, malformed UTF-8, explicit error/fatal/panic diagnostics,
Git input failures, partial scans and timeout markers. A successful log must
retain its final newline and exactly one ordered commits/bytes/no-leaks summary,
with the no-leaks summary at the end. Both reported counts must be positive
ASCII decimals without leading zeroes. The
[zero-census counterexample](https://github.com/neuron7x/KORPUS/pull/116#issuecomment-7027287930)
is refused independently for zero commits or zero bytes, including when the other
count is positive and the findings report is empty. Required framing detects
truncation that loses the summary; positive reported counts and a complete-looking
log still do not independently prove successful Git EOF or complete detector
consumption. Source before/after equality verifies the admitted current tree,
not every historical object's readability.

The v2 change adds no scanner execution, API request, engine substitution,
rule/baseline adjustment, timeout extension or resource allowance. Historical
seven-member v1 artifacts remain historical evidence; current admission requires
the v2 eight-member contract and a fresh original hosted artifact.

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

Gitleaks receives `--timeout 230` with a uniform 240-second parent bound. Image
pulls also retain 240 seconds; cleanup queries retain 10 seconds. These are the
original limits required by the
[coordinator instruction](https://github.com/neuron7x/KORPUS/issues/97#issuecomment-7021766089)
and [PR instruction](https://github.com/neuron7x/KORPUS/pull/116#issuecomment-7021753040).
The subsequent 600/900-second native and 630/930-second parent allocations
violated that bound. Their measurements remain diagnostic observations and do
not qualify the policy. The pinned v8.30.1
[command context and failure handler](https://github.com/gitleaks/gitleaks/blob/v8.30.1/cmd/root.go)
use a cancellation context and a nonzero exit for scan errors, including partial
scans. A nonzero exit remains a failure even when a native report exists. The actual
full-history scan must still complete successfully in hosted CI.

An earlier diagnostic run
[44602028545, job 135835685439](https://github.com/neuron7x/KORPUS/actions/runs/44602028545/job/135835685439)
used tree `b01163f098d842c3689768c8128e7f7dc53c75f1`. Its 230-second native deadline
interrupted the history scan after approximately 303.72 MB and 761 commits; the
partial report correctly remained a failed execution. Pulls took about eight
seconds and the four other scanners about 4.3 seconds combined.

Two subsequent native runs used the 600-second allocation:

- [Run 44607373087, job 135854556828](https://github.com/neuron7x/KORPUS/actions/runs/44607373087/job/135854556828)
  on head `ae602e01`, merge `64b52682`, tree
  `3fec84f067b1009e227c8c90535814749b54f19e` completed its configured patch stream
  with exit 0 in 338.984 seconds. Gitleaks reported 1296 commits,
  544,176,163 scanned bytes and no leaks under the configured rules and baseline.
- [Run 44609740798, job 135863006310](https://github.com/neuron7x/KORPUS/actions/runs/44609740798/job/135863006310)
  on head `16bfba03`, merge `59249b2e`, tree
  `527619ad70c19106814236d13c47ac4bd5e9a298` reached the 600-second native deadline
  and exited 1 after 600.521 seconds. Its partial scan reported 1114 commits and
  501,815,047 scanned bytes. Zero findings in that partial report did not qualify
  as a completed clean scan. Pulls took approximately 7.36 seconds combined, and
  the four other scanners exited 0. All three container receipts confirmed absence
  after natural removal; forced cleanup after a parent timeout was not exercised.

A later diagnostic run used the 900-second allocation:
[run 44616015657, job 135884788331](https://github.com/neuron7x/KORPUS/actions/runs/44616015657/job/135884788331)
on head `cf256458`, merge `a879c4ca`, tree
`deeed68d01b6204ed1c887e596c1bdbe0bf3de7f` completed its configured patch stream
with exit 0 in 431.126 seconds. Gitleaks reported 1297 commits and
544,179,939 scanned bytes. This run also exceeded the required 230-second budget.

Those runs passed only a revision to Gitleaks' `--log-opts`. The pinned
[Git source implementation](https://github.com/gitleaks/gitleaks/blob/v8.30.1/sources/git.go)
therefore ran `git log -p -U0 <sha>` without requesting merge diffs. Git normally
suppresses merge patches in that mode, so merge-only material was omitted. Even
the exit-zero results do not establish complete reachable-history content coverage.
Reported commit counts and raw-fragment byte totals are scanner observations,
not a complete commit census or a measure of all decoding and regular-expression
work. No completed scan satisfying the original budget and corrected scope has
been established.

The observed scan durations differ; these measurements do not establish the cause.
CPU and memory limits, isolation, pins, rules, baseline, redaction, strict exit
predicates and cleanup requirements remain unchanged in this candidate.

## Corrected history input and bounded performance experiment

The exact log options are `<sha> --full-history --diff-merges=first-parent`.
The [Git diff contract](https://git-scm.com/docs/git-log/2.31.0#Documentation/git-log.txt---diff-mergesltformatgt)
distinguishes this merge-diff mode from the separate `--first-parent` traversal
option. The latter is absent: all reachable parent histories remain eligible.
Each merge emits its textual diff against its first parent, while ordinary
commits on every parent history are still traversed. Under ordinary Git text-diff
semantics this retains added text from every reachable commit, including
merge-only additions. It does not promise every parent-relative delta or finding
fingerprint, binary-blob coverage, or detection of every secret. Combined diffs
are not substituted for the ordinary unified patches consumed by the pinned parser.

The regression fixture contains two-parent and octopus merges, novel merge text,
and side-branch text deleted before merging. The selected stream includes all
nine reachable commits and all nine required neutral markers. Controls detect
omitted merge patches and first-parent-only traversal. A separate-per-parent
stream covers the same markers with more patch bytes in this fixture. These
Git-only tests establish input semantics; they do not measure native detector
performance or establish completion on the repository's real history.

Only the Gitleaks container receives the fixed environment value `GOMAXPROCS=2`,
before its immutable image argument. Its existing `--cpus=2` and `--memory=2g`
limits are retained. The pinned
[Dockerfile](https://github.com/gitleaks/gitleaks/blob/v8.30.1/Dockerfile) uses a
Go 1.24 builder; the [Go runtime documentation](https://go.dev/blog/container-aware-gomaxprocs)
describes the later Go 1.25 change to container-aware scheduler defaults.
Aligning scheduler parallelism with the existing quota is a falsifiable
performance candidate. The runner's actual scheduler default and the resulting
speed difference have not been measured. No resource limit, decoding depth,
garbage-collector setting, image, rule or baseline is changed.

Gitleaks receives `--diagnostics cpu --diagnostics-dir /output/gitleaks-profile`.
Its pinned [diagnostic implementation](https://github.com/gitleaks/gitleaks/blob/v8.30.1/cmd/diagnostics.go)
writes `cpu.pprof` in that directory and finalizes CPU profiling when the command's
normal completion/error handler runs. The dedicated path
`var/source-security/gitleaks-profile/cpu.pprof` is uploaded with the diagnostic
logs, outside the eight-member v2 evidence artifact. It cannot replace a
native report, a zero exit, source identity, or verified cleanup. An abrupt parent
timeout or job cancellation may prevent profile finalization; a missing or partial
profile is not a successful scan. CPU-only profiling enables neither an HTTP
listener nor heap/trace collection. Its timing overhead is part of the same
230/240-second experiment, not an allowance beyond the policy.

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
They do not establish native Docker execution in this local environment. The
first hosted execution of the corrected configuration failed, as recorded below;
the local controls supply no successful scan, complete admission or production
authority.

## Native corrected-scope result: original budget still unmet

Head `0e39b07bb9e4ad5d6d90dfcc3500a64d6f1a48ff`, tree
`99223f296f961d454778b569ebfb42d2f2879eb6`, ran as merge checkout
`fa7009f2ac833e616470da807ab45e35b9c20c95` in
[CI 44621210256/1, source-security job 135903048216](https://github.com/neuron7x/KORPUS/actions/runs/44621210256/job/135903048216).
Gitleaks returned **exit 1 after 230.407176 seconds**, with a native context
deadline and a **partial** 1,190-commit / 597,634,761-byte scan. The original
230-second native and 240-second parent limits were configured. Six findings
were retained. This is a failed qualification, including if the remaining
software checks succeed.

All four other scanners returned zero. The three image pulls completed in
13.662595 seconds total. All three container records confirmed natural absence;
no forced cleanup after a native parent timeout occurred. Six native output
hashes, the 29-package scanner-toolchain census and the source snapshot were
independently verified. The snapshot contains 1,937 files with SHA256
`6b7df8e30203f352fc3784fa0252b7dee84b7ab9758180fe2aca134ba42ba290`.

| Original artifact | GitHub SHA256 |
| --- | --- |
| Evidence 14577755650 | `31aefdfa351ded59db54995eed699de80c84ea1af2af1933374b8306ca0e3fa1` |
| Diagnostics 14577905969 | `c024a34aad9b0bc3e84443407195c4900b0d739ac98aeef616e9f7f00671a66e` |
| Scanner toolchain 14577831159 | `292546164484e9c9ab923b7591dc38b9696bc9ae7b3d64948d5af466bd768a11` |

Each original ZIP matched its authenticated size, digest and CRCs. The finalized
CPU profile is 65,081 bytes, SHA256
`b3e685681e326d01d3b934cd68f1ca2767b48eef143aadcda3d43cfe57781455`.

### Measured CPU work

The CPU profile records 230.199646515 seconds of duration and 448.15 sampled CPU
seconds, approximately 1.947 CPU-seconds per elapsed second. Stacks containing
`regexp.(*Regexp).doExecute` account for 439.36 CPU seconds, or 98.039% of the
sampled CPU total. Rule matching accounts for 371.05 cumulative CPU seconds;
decoder processing accounts for 66.52. These cumulative stack measurements are
not disjoint categories to sum.

This observation identifies regular-expression work as the dominant cost in this
partial run. It does not measure the complete history's CPU requirement, prove
host throttling, or isolate the effect of `GOMAXPROCS`: the corrected merge stream
also changed the workload. The profile covers the Go scanner process and excludes
Git subprocess CPU. It supplies no evidence for a material gain from arbitrary
garbage-collector tuning and no authority to raise the preserved time or resource
limits.

### Six reports concern already-baselined file bytes at a merge

All six `generic-api-key` records refer to historical merge commit
`81bbfaa3ac63ae626476989135f5d17ee3b73654`. Authenticated Git tree objects show
that their entire file blobs equal versions already represented in the unchanged
16-entry baseline:

| Path | Reported lines | Existing baseline-associated commit | Identical Git blob |
| --- | --- | --- | --- |
| `docs/audit/closure/KORPUS_v5_FINDINGS_CLOSURE.csv` | 62, 72 | `8282281cec9b58deb029b0123fd9b4e5f01c0cd1` | `9c9481223b40eee9c1595ef1cab9c5426aaa16d7` |
| `docs/audit/closure/KORPUS_v5_REMAINING_DEBT.csv` | 45, 52 | `8282281cec9b58deb029b0123fd9b4e5f01c0cd1` | `c718ef0f3e449850f01b57cf238bc9a714ebed8c` |
| `docs/audit/source/KORPUS_v4_REMEDIATION_BACKLOG_2026-08-01.csv` | 62, 72 | `0c04b9efef53f988056c4c9e2ed96afab4798bf9` | `66444c3fff19ee6166bb0113f60b216ddd8d2c5f` |

Each report has a baseline counterpart with matching rule, path, line/column
coordinates and redacted match. Whole-file Git blob equality establishes the
material comparison; equality of redacted secret fields is not used as proof.
The pinned [Gitleaks baseline predicate](https://github.com/gitleaks/gitleaks/blob/83d9cd684c87d95d656c1458ef04895a7f1cbd8e/detect/baseline.go)
compares commit and authorship metadata and explicitly omits the displayed
fingerprint from that comparison. New merge attribution therefore causes these
existing bytes to be reported again.

These six reports establish no new file material. Redacted output alone does not
establish credential validity, fixture neutrality, or permission to broaden a
suppression. The baseline used by that native run had 16 records and SHA256
`605fb1f1823121075ceffc7ee1d352432f0cdf36a3f8470f7e3a9c41ddd2ab6a`.
No baseline, rule, ignore or history change was part of that measured revision.
Partial findings cannot be treated as the complete finding census.

The subsequent [six-record reconciliation proposal](audit/gitleaks-merge-baseline-reconciliation-2026-11-19.md)
uses the authenticated identical blobs and the historical owner's explicit
audit-false-positive dispositions. It appends only the six complete redacted
merge-attributed records, preserves all 16 existing records, and records the
resulting 22-entry baseline SHA256
`c460c0623fe7c8acde749f134fc90564c22c387623be803763cd15e9bd848f91`.
This is a narrowly scoped draft source change for independent review, not a
path-wide exception or a complete-scan result. Pinned rules, matcher semantics,
ignore file, history and the original timing/resource limits remain unchanged.
The original native budget failure remains unresolved.

