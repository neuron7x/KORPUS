# Source-pinned stdlib diagnostic for issue #102

This experiment has **no scanner admission authority**. The canonical Gitleaks
image, all detector rules, the 22-record baseline, full-history arguments,
230-second native deadline, 240-second parent deadline, 2 CPU and 2 GiB sandbox
remain unchanged. Its receipt uses `korpus.scanner-stdlib-diagnostic.v1`; its
artifact is `scanner-stdlib-diagnostic-<attempt>`. Neither is a source-security
receipt or release attestation.

## Causal observation

The native failure on the earlier PR subject was a deadline, not a positive
secret finding. The original native CPU profile placed 364.87 CPU seconds in
the first `FindAllStringIndex` call and only 4.18 seconds in the repeated call.
Reusing the first match list therefore did not address the dominant cost and
was not proposed as the repair.

A source-pinned, local, non-Docker profile of upstream Gitleaks
`83d9cd684c87d95d656c1458ef04895a7f1cbd8e` used the same stdlib engine, default
rules, history arguments, baseline and 230-second deadline. Labels around the
unchanged first finder identified these costs in the partial scan:

| Rule | Labelled CPU seconds |
| --- | ---: |
| `generic-api-key` | 164.7 |
| `lob-api-key` | 79.3 |
| `lob-pub-api-key` | 64.1 |
| `gocardless-api-token` | 31.3 |

The four rules accounted for 92.47% of 367.0 labelled CPU seconds. They share
the exact leading expression `(?i)[\w.-]{0,50}?`.

## Restricted transformation and semantic argument

Let `P` be the capture-free optional prefix `[\w.-]{0,50}?`, and let `R` be
the remainder of one of the four exact default expressions. Both the original
and the precheck retain the leading `(?i)` flag and use Go's standard-library
regexp implementation on the **same complete `currentRaw` input**.

A successful match of `P R` contains a successful match of `R` at the end of
the consumed prefix. Conversely, every match of `R` is a match of `P R` with
an empty prefix. The existence predicate is therefore equivalent. A negative
suffix `MatchString` can avoid the expensive original finder on a fragment
that has no possible original match.

When the precheck is positive, the original `FindAllStringIndex` runs unchanged.
The precheck never supplies match positions, captures, secrets, ordering or
fingerprints. In particular, suffix offsets are not equivalent to original
offsets when the original match includes a leading identifier prefix.

The cache binds an exact rule ID, full original expression and regex pointer.
It checks the expression again at use time. A custom rule, changed pointer or
in-place `Regexp.UnmarshalText` replacement falls back to the original finder.
This last guard closes an independently reproduced stale-pointer false
negative in an earlier diagnostic draft. The precheck reads `currentRaw` on
each decoding pass; it does not substitute `fragment.Raw` or slice the input.

The independent standard-library differential review exercised 141,810 cases:
94,378 cases for the four actual expressions and 47,432 contextual models,
including invalid UTF-8, control bytes, Unicode simple-fold cases, inline flag
changes, prefix-length boundaries, empty matches and longest-match mode. It
found no mismatch. This finite test supports the argument; it is not a proof
by enumeration of every possible input. The shipped Go regression additionally
compares complete finding records through decoding and the in-place mutation
fallback. The proof and tests do not qualify the alternate RE2 engine.

## Observed local performance and limits

All three rows below are **local diagnostics without the Docker/cgroup
boundary**, using `GOMAXPROCS=2` and the unchanged 230/240-second limits.

| Source subject | Variant | Wall seconds | Exit | Native reported commits | Native reported bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| `e66492acbcfcee9cec720c629971295c5f8d8d01` | Labelled original stdlib | 230.46 | 1 | 951 | 410,421,817 |
| `e66492acbcfcee9cec720c629971295c5f8d8d01` | Optional-prefix diagnostic | 186.00 | 0 | 1,416 | 676,793,574 |
| `aa400d30f7e582f28cbe9f8a1573cb89fc7e2a2b` | Guarded optional-prefix diagnostic | 187.64 | 0 | 1,464 | 678,396,225 |

The first row logged a partial scan and a context deadline. The latter two
logged no leaks and no partial/deadline message. These are observations of
the invocations, not independent proof of Git EOF or complete detector
consumption. The diagnostic receipt deliberately keeps
`history_completion_established=false` and
`eof_status=NOT_INDEPENDENTLY_OBSERVED`, including after a zero exit.

The guarded local candidate binary was rebuilt from a fresh upstream archive
with the exact patch recipe and was bit-identical:
`f81d21c457aed77ba431b87a4e21e7a98280f2b3235c6901bd351695c9229bcd`.
The later test-only fixture revision reproduces this same binary digest.
Hosted output digests are observations and must be read back from the actual
new workflow; the local binary digest is not a substitute for that evidence.

The Go regression generates new provider-shaped positive fixtures from a
repeated public hexadecimal alphabet at runtime. These replace three complete
handwritten synthetic literals; none of the former byte sequences is retained
or reconstructed. The regression still requires findings for all four exact
rule IDs and compares complete records, decoding, original match offsets and
the in-place regex mutation fallback. This fixture revision leaves runtime
scanner code unchanged.

A publication attempt for frozen tree
`2f36bf5993ca362c9819c80f7035d4df30c8caef` stopped at GitHub's create-tree
request with HTTP 422, `Secret detected in content`. No tree, commit or ref was
created. The response supplied no rule or location; the exact rejection cause
remains **UNKNOWN**. A read-only scan of all 20 complete changed blobs with the
unmodified stdlib binary and embedded default rules returned zero findings.
That result does not invalidate GitHub's separate protection. Independent
source review identified the three synthetic provider-shaped literals in the
Go test patch. This revision removes those literals as a source-safety
improvement, without claiming that their removal explains the rejection.
No protection bypass, exclusion or scanner-rule change is part of this work.

The revised complete changed blobs are scanned again with the original stdlib
binary, without a baseline or added exceptions. Neutral text filenames avoid
path-based allowlisting. The three former sequences are absent from the entire
revised tree. The standalone format check finds no complete GoCardless/Lob-shaped
literals in the 20 changed blobs using the checked token formats. These local
checks do not authorize publication or substitute for GitHub's own decision.

## Native experiment and provenance

The separate `scanner-stdlib-diagnostic-nonauthoritative` workflow:

1. Checks out the complete exact event history without persisting credentials.
2. Obtains Go 1.24.11 through a commit-pinned setup action. Before the build
   runner executes Go, it verifies the executable and all 14,178 files /
   253,338,050 bytes against the pinned official toolchain inventory.
3. Fetches the exact upstream commit and verifies its Git tree and complete
   SHA256 file inventory. Default rules, `go.mod` and `go.sum` are additionally
   checked at each stage.
4. Applies the exact profiling patch and builds a control. Applies the exact
   optional-prefix patch and builds a candidate. Both builds use
   `GOTOOLCHAIN=local`, `GOENV=off`, empty `GOFLAGS`, `CGO_ENABLED=0`, read-only
   modules, path trimming and no VCS-derived build metadata. Selected regexp
   source must be exactly `stdlib_regex.go`. Both run the upstream detector and
   decoder test suites; the candidate also runs the new differential tests.
   A source-provided `.gitleaks.toml`, including a dangling symlink, refuses
   this embedded-default-rule experiment before a build or scanner invocation.
5. Executes both binaries in the existing digest-pinned scanner container
   sandbox. Their UTF-8 controls must each find both the valid and invalid
   input. Synthetic default-rule controls must exercise all four optimized
   rules. Complete native finding records must match between variants inside
   the owned temporary directory; their hashes are recorded without their text.
6. Runs both full-history invocations with the existing canonical arguments
   and exports bounded structural summaries only after owned container cleanup
   is proven. Summaries contain byte counts, SHA256 values, numeric native
   census observations and fixed diagnostic booleans. Raw logs, full findings,
   execution-file bytes and CPU profiles remain in the temporary directory
   and are removed with it. Source and binary identities are checked again.
   A partial candidate leaves the diagnostic incomplete.

An independent native synthetic-commit witness confirmed that `--redact`
redacts `Secret` while preserving context in `Match` and arbitrary commit
metadata in `Message`. Consequently, no corpus-derived free-text field is
uploaded. CPU profiles receive only byte counts and hashes because their
string table is not independently validated by this exporter. Complete
record comparison still happens before those private files are removed.
The existing alternate-engine diagnostic now delegates to the same safe projection.
Its parser and admission semantics remain unchanged. Mutation M774 continues to
exercise validating different bytes; its target moves with the shared validator.

The build receipt records source, patch, compiler, build-command and binary
digests. It explicitly records `trusted_build_attestation=false`: reproducing
a build does not register a trusted builder or supply an external signature.
The entire experiment still has `production_authorized=false` and
`drop_in_equivalence_established=false`.

The input inventory hashes each regular file's relative POSIX path, semantic
mode and SHA256, sorted by path components. The source inventory also hashes
symlink targets without following them; the compiler inventory refuses all
symlinks. SHA256 checks of the complete input trees refuse unexpected source,
compiler files, executable-mode changes or additions before the build.

## Evidence sources

- [PR #116](https://github.com/neuron7x/KORPUS/pull/116) and
  [issue #102](https://github.com/neuron7x/KORPUS/issues/102).
- [Original failing canonical CI](https://github.com/neuron7x/KORPUS/actions/runs/44656066746),
  source-security job `136022464344` and source-security diagnostics artifact
  `14593412419`.
- [Current integrated-subject canonical CI](https://github.com/neuron7x/KORPUS/actions/runs/44877531371),
  source-security job `136765426967`; this still timed out with the canonical
  scanner unchanged.
- [Pinned upstream detector source](https://github.com/gitleaks/gitleaks/blob/83d9cd684c87d95d656c1458ef04895a7f1cbd8e/detect/detect.go).
- [Official Go 1.24.11 distribution](https://go.dev/dl/go1.24.11.linux-amd64.tar.gz),
  SHA256 `bceca00afaac856bc48b4cc33db7cd9eb383c81811379faed3bdbc80edb0af65`.

Native paired qualification remains pending until a reviewer publishes this
diagnostic candidate and the exact resulting hosted artifacts are read back.
No canonical scanner promotion follows automatically from this workflow.
