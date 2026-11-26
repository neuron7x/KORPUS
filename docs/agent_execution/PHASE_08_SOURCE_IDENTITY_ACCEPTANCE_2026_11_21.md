# Phase 08 source-identity precursor: issues #4 and #16

## Scope and disposition

This change addresses the shared source-digest framing requirement in original
issue #4 and supplies explicit orchestration-mutation witnesses for original
issue #16 under execution issue #105. It does not close the aggregate phase,
qualify a production release, or satisfy the artifact-internal signing work in
phase 07. The original reviewed framer tree
`f52bc3c995f89faffe722e530f04865b8b2ae5aa` was based on commit
`981794e6968ca7e169c9326369d9a03a4764b592`. It was checkpointed locally as
`8d8c80d41edbd4d8d6998c59af95a955560099c8` before an ordinary merge with the
published phase-02 commit `7877507569863d45d47b63608f27c2915f74bab7` (tree
`9bda6cbe527ef6fa721f5b1f9e80db7949a8cd54`). The initial remote publication is
planned as a normal child of `7877507` alone. The local checkpoint records the
reviewed bytes and is not a required remote or published parent. Phase 01/02
and the other aggregate-phase prerequisites retain their own acceptance gates.

## Observed defect and change

Before this change, `compute_source_digest` and `digest_source_records` each
implemented the complete SHA-256 domain/path-length/path/content-length/content
framing loop. They agreed on the measured inputs, but the duplication violated
#4's explicit single-implementation requirement. No digest discrepancy is
claimed for the previous implementation.

`_digest_source_streams` now owns the only framing implementation. The live-file
adapter supplies bounded one-MiB reads, and the committed/package-record adapter
supplies its already captured bytes. Both use the existing
`korpus-source-digest-v2\0` domain, the same sorted input order, four-byte path
length, eight-byte content length, and UTF-8 path encoding. The live adapter
closes its current file on normal completion and on a size-change refusal.
Evidence scope and metadata-free source admission are unchanged. The existing
300-line module ceiling is unchanged; the module contains 291 physical lines.

## Historical compatibility and causal controls

The original fixed-vector and boundary controls passed against the original runtime
before the refactor: 15 passed, zero failures/errors/skips. This is a healthy
format baseline, not a fabricated functional failure. The identified failure
was the two framing implementations in source.

A separate read-only experiment recomputed all 1,940 evidence-source records
from immutable predecessor Git objects, independently checked 1,941 blob object
hashes including the source manifest, and compared three paths:

- an independent transcription of the published framing format;
- the new `digest_source_records` implementation;
- the new live-file implementation over an explicitly metadata-free export.

All three returned
`f937745ea982256717d4a388ee4f6fb5204c106cec1c754e26ed3ae08122bf51`.
This is a compatibility experiment on the predecessor's input bytes, not the
new candidate's source identity or trusted-Git release qualification.

Focused execution of the original reviewed checkpoint covered the new module plus existing evidence
provenance, evidence without Git, common provenance, and package semantics:
95 collected, 94 passed, one skipped, zero failures/errors. The skipped existing
integration case requires operational eval/mutation/migration/scale artifacts
that were absent in this local run; it is not credited as passed. Ruff check and
format, strict mypy of the changed application module, and all 771 existing
module-budget checks passed without raising a ceiling.

The new controls include fixed empty/binary/Unicode framing vectors; zero,
one-byte, one-MiB boundary and multi-MiB streamed inputs; actual growing and
shrinking source files with refusal and handle closure; and Makefile/workflow
changes that alter both live and captured-record identity. A documentation-only
edit preserves the evidence digest. Coherently rebuilding package inventories
after an orchestration edit cannot make an old research-evidence digest valid.

Four isolated direct pytest mutation experiments produced the intended assertion
failure (exit 1), with zero collection/runtime errors or skips:

| Mutant | Causal defect observed |
| --- | --- |
| M62_DIGEST_DROPS_LENGTH_FRAMING | Path/content boundary collision after length framing is removed from the sole framer. |
| M849_SOURCE_STREAM_SIZE_CHANGE_ACCEPTED | A changed-size source file is accepted instead of refused. |
| M850_MAKEFILE_OMITTED_FROM_EVIDENCE_SCOPE | A Makefile change no longer changes evidence identity. |
| M851_WORKFLOW_OMITTED_FROM_EVIDENCE_SCOPE | A workflow change no longer changes evidence identity. |

M62 retains its existing failure hypothesis and test; only its exact source
anchor follows the refactor. M849-M851 are new independent fault definitions.
No other existing mutation definition or denominator is intentionally changed.

## Integrated source compatibility

The integrated candidate retains the exact reviewed `provenance.py` bytes
(SHA-256 `678e571bf97770820ff243b26ad27e83d0cdb2b6c16221dec02771adf6b38ce9`)
and the original framing tests. The mutation merge preserves the same M62
failure hypothesis and retargeted anchor, M849–M851, and every incoming
M852–M860 definition. Its combined catalogue has 717 definitions. All 773
budget entries equal the published phase-02 parent's entries; no ceiling moves.

A new exact-input experiment verified all 3,169 transported Git blobs and modes,
then selected **1,947 evidence-source records / 37,280,451 bytes** using the
unchanged published source-scope rules. On that one sorted input map, four
computations agree:

- an independent transcription of the published byte format;
- the actual historical `digest_source_records` function extracted from the
  immutable `981794e6` source, without the refactored helper;
- the unchanged reviewed record adapter;
- the unchanged reviewed live adapter over a metadata-free export with its
  source manifest regenerated by the unchanged producer.

All four return
`da9f8f89013ae9461cce97e559e107b24b67edbdb8f2ebaff81b9e7a5c369174`.
The canonical input-map digest is
`06735319d5eb52f9f272c729756a0eb14c384ba44131926a3c5b1817718ac586`;
the exact serialization and every path/blob/size/content-hash record are retained
in the local proof receipt. The live adapter selects exactly those input paths.

This new digest belongs to the integrated input map. The earlier 1,940-record
`f937745e…` result remains a historical format proof and is not relabelled as the
new source identity. Documentation and the two root identity files are outside
the evidence-digest scope. Final freezing rechecks the entire input map against
the final blobs after updating this documentation and regenerating
`SOURCE_MANIFEST.json` / `PACKAGE_BUILD.json`; the full source-manifest identity
is a separate value recorded by that freeze.

The combined local compatibility selection contains 278 cases: **268 passed,
10 skipped**, zero failures/errors. It combines the framing/provenance/package
controls with the retained phase-01/02 compatibility selection. Nine skips are
the explicit native PostgreSQL approval/seal cases; the tenth is the existing
foreign-evidence integration case whose eval/mutation/migration/scale artifacts
are absent. These skips remain unexecuted predicates. The final freeze binds
the exact command and subsequent source checks to the integrated subject.

These are ordinary Git-object transport and metadata-free format experiments.
They do not satisfy trusted local Git qualification, native CI, canonical mutation
execution, release verification or full phase-08 acceptance.

## Reproduction

From a correctly provisioned repository root, the focused command is:

```sh
python -m pytest apps/api/tests/test_source_digest_framing.py apps/api/tests/test_evidence_provenance.py apps/api/tests/test_provenance_without_git.py apps/api/tests/test_one_provenance_surface.py apps/api/tests/test_package_semantics.py -q --no-cov
```

The exact executed node census is retained in the local JUnit receipt; canonical
CI must execute the final candidate with its complete existing gates. The
complete compatibility proof and direct-mutant diagnostic receipts are retained
with this execution session and their digests are summarized in the adjacent
JSON record. They confer no release authority.

## Remaining gates and limits

The local canonical bounded mutation/build paths remain NOT_EXECUTED because
the unchanged trusted-tool and child-ownership checks reject this execution
host. Neither guard was patched, bypassed, or represented as a passing run.
Ordinary Git-object transport and independently checked metadata-free derivation
are explicitly narrower experiments. The source-manifest and package identity
are regenerated and verified during the candidate freeze; current-head
native CI, canonical mutation execution, package verification, independent
source review and required submitted nonauthor review remain separate gates.

Production authorization is false. No corpus, credentials, running deployment,
release signing key, or production data was used.
