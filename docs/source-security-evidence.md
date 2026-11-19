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

## Native reports and receipt

The artifact `source-security-evidence-${run_attempt}` has exactly seven members:

| Member | Meaning |
| --- | --- |
| `source-security-receipt.json` | Run/repository/attempt, checkout commit/tree, before/after source binding, tool identities, five real execution outcomes, and hashes of the other six members |
| `gitleaks.json` | Native redacted findings array; admitted only when empty |
| `pip-audit-runtime.json` | Native audit of every runtime lock pin; no skipped dependency, vulnerability, or repair |
| `pip-audit-dev.json` | Native audit of the exact union of runtime and development pins |
| `trivy.json` | Native configuration results with a positive census of passing HIGH/CRITICAL rules and no unaccepted failure |
| `tree-sbom.cdx.json` | Actual Syft directory discovery in CycloneDX 1.6, including native tool/source metadata |
| `lock-sbom.cdx.json` | Deterministic complete application lock component universe in CycloneDX 1.6 |

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

Every scanner is attempted even when an earlier scanner fails. The producer
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

Upstream format and command references used for this contract:

- [pip-audit 2.10.1 native JSON formatter](https://github.com/pypa/pip-audit/blob/v2.10.1/pip_audit/_format/json.py)
- [Syft 1.44.0 CycloneDX metadata](https://github.com/anchore/syft/blob/v1.44.0/syft/format/common/cyclonedxhelpers/to_format_model.go)
- [CycloneDX 1.6 schema](https://github.com/CycloneDX/specification/blob/1.6/schema/bom-1.6.schema.json)
- [Trivy 0.70.0 native report](https://github.com/aquasecurity/trivy/blob/v0.70.0/pkg/types/report.go)
- [Trivy result filtering and rule census](https://github.com/aquasecurity/trivy/blob/v0.70.0/pkg/result/filter.go)
- [Gitleaks 8.30.1 native JSON reporter](https://github.com/gitleaks/gitleaks/blob/v8.30.1/report/json.go)
