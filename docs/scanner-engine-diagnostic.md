# Alternate Gitleaks engine diagnostic

This experiment measures one fixed official release binary in the existing scanner
sandbox. It has no source-security admission or production authority. The original
scanner command, image, rules, baseline, workflows and acceptance predicates remain
unchanged.

## Why a separate experiment is necessary

The v8.30.1 release configuration enables the `gore2regex` build tag, while the pinned
Dockerfile uses the Go standard-library regex implementation. The alternate engine
uses go-re2 v1.9.0 and its embedded C++ RE2 through wazero. That is a plausible
performance variable, not evidence of improved speed or equivalent detector behavior.
The engine initializes before Gitleaks starts its native scan timer; the unchanged
240-second parent deadline therefore includes startup as well as the scan.

The release archive is fixed to asset 378332058 of release 299662760:

| Identity | Value |
| --- | --- |
| Tag | v8.30.1 |
| Intended source commit | 83d9cd684c87d95d656c1458ef04895a7f1cbd8e |
| Archive bytes | 8,230,402 |
| Archive SHA-256 | 551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb |

These values establish fixed content identity. The inspected release does not provide
an independently verified binary build attestation. Archive members, extracted binary
hash and actual version/engine messages are recorded only after native observation.

The canonical full invocation has no `--config` override, and the repository has no
root configuration file named .gitleaks.toml. It selects embedded default rules with
the existing ignore file and baseline. The diagnostic policy records this rule source;
equality of the embedded rule bytes between the pinned image and release binary is
not independently verified. The diagnostic does not create a custom rule configuration
for the full invocation.

Primary sources: [release configuration](https://github.com/gitleaks/gitleaks/blob/83d9cd684c87d95d656c1458ef04895a7f1cbd8e/.goreleaser.yml),
[Dockerfile](https://github.com/gitleaks/gitleaks/blob/83d9cd684c87d95d656c1458ef04895a7f1cbd8e/Dockerfile),
[official release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1), and
[go-re2 behavior differences](https://github.com/wasilibs/go-re2/blob/f2f12a069bdbc41d9ead16609f20427c116f3870/README.md).

## Native controls and interpretation

The workflow first observes both binaries' version output and debug engine markers.
A disposable Git fixture contains two neutral lines matched by a custom anchored rule.
One line contains valid UTF-8; the other contains byte 0xff between the required BEGIN
and END markers. The expected observation is that stdlib reports both lines and go-re2
reports only the valid line. The experiment records the actual findings before deciding
whether that expected difference was observed. An unexpected pattern stops the full
invocation; it cannot establish equivalence.

A separate two-commit fixture deletes an old neutral marker from its current tree.
Both binaries must first find that historical marker in the intact history. Only that
fixture's verified loose historical blob is then removed. Its HEAD, current tree and
current file remain unchanged. Independent bounded Git log/fsck invocations establish
the damaged history; the native scanner exits, redacted findings and debug errors are
recorded without presuming that Gitleaks will propagate the input error. No canonical
repository object is modified, and no PATH shim substitutes for Git.

Even a zero scanner exit cannot independently establish complete Git EOF. In the pinned
source, the Git process wait error is debug-logged, and a detector fragment-error path
logs its input error without necessarily returning it to the CLI. The canonical scan
therefore always retains `eof_status: NOT_INDEPENDENTLY_OBSERVED` and
`history_completion_established: false`, regardless of the tiny fixture outcomes.
See the pinned [Git source](https://github.com/gitleaks/gitleaks/blob/83d9cd684c87d95d656c1458ef04895a7f1cbd8e/sources/git.go),
[detector](https://github.com/gitleaks/gitleaks/blob/83d9cd684c87d95d656c1458ef04895a7f1cbd8e/detect/detect.go), and
[CLI](https://github.com/gitleaks/gitleaks/blob/83d9cd684c87d95d656c1458ef04895a7f1cbd8e/cmd/root.go).

## Bounds and output boundary

The archive download permits at most three HTTPS requests, two redirects, a 45-second
total Linux wall timer, ten-second socket operations and the exact pinned body size.
Only GitHub and its two explicitly named release asset hosts are allowed; no token is
sent. A bounded in-memory archive inspection rejects traversal, duplicate or nonregular
members and extracts only the x86-64 ELF into owned temporary storage.

The binary is mounted read-only and executed only inside the existing digest-pinned
Gitleaks image. CPU 2, memory 2 GiB, PID 256, offline networking, read-only root filesystem,
capability removal, no-new-privileges, owned container cleanup and GOMAXPROCS=2 remain
the existing settings. Neutral scans have a 15-second native limit. The full invocation
reuses the exact canonical arguments: native 230 seconds, parent 240 seconds, full
reachable history with first-parent merge diffs, 22-record baseline, full redaction,
default decode depth 5 and CPU profiling. It does not add first-parent traversal.

The separate job has a 25-minute deadline. The producer admits each native invocation
only while at least five minutes remain in its own 20-minute measurement budget.
Unverified cleanup or incomplete prerequisite execution stops subsequent probes.
The reported wall duration includes owned cleanup; native profile timing is a distinct
measurement. Container peak memory and OOM state are not inferred from Docker-client
resource usage. There is no performance ratio or engine-causality conclusion from
different runners or cache states.

Native files stay in temporary storage. Only named, regular, bounded logs, execution
records, redacted reports and the CPU profile are copied into the diagnostic artifact.
The export rejects symlink files/parents, oversized data, unexpected finding fields,
non-null raw fragments and secrets that lack the full-redaction marker. It preserves
accepted native bytes; it does not rewrite a failing report. Finding metadata and
surrounding match context are not claimed to be globally secret-free. Downloaded
archives, binaries, fixture sources and raw Git history are never exported.

The artifact uses the separate scanner-engine-diagnostic name and diagnostic schema.
Every receipt sets `not_authoritative: true`, `production_authorized: false`,
`drop_in_equivalence_established: false`, `performance_ratio_established: false` and
`engine_causality_established: false`. A recorded clean invocation is a measurement,
not acceptance of the alternate engine. No result from this workflow enters hosted
source-security evidence admission.

The executable entry point is `scripts/run_scanner_engine_diagnostic.py`; the separate
workflow is `.github/workflows/scanner-engine-diagnostic.yml`. Native measurements are
pending until an exact published head actually executes this workflow.
