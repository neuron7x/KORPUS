# Proposed reconciliation of six historical Gitleaks records

Status: proposed source change for independent review. No main merge, scanner
acceptance or production authority is granted by this note.

## Exact evidence and bounded change

[CI 44621210256/1, job 135903048216](https://github.com/neuron7x/KORPUS/actions/runs/44621210256/job/135903048216)
tested head `0e39b07bb9e4ad5d6d90dfcc3500a64d6f1a48ff`, merge checkout
`fa7009f2ac833e616470da807ab45e35b9c20c95`, tree
`99223f296f961d454778b569ebfb42d2f2879eb6`. Its original evidence ZIP,
[artifact 14577755650](https://github.com/neuron7x/KORPUS/actions/runs/44621210256/artifacts/14577755650),
has SHA256 `31aefdfa351ded59db54995eed699de80c84ea1af2af1933374b8306ca0e3fa1`.
The native report member [gitleaks.json](https://github.com/neuron7x/KORPUS/actions/runs/44621210256/artifacts/14577755650)
belongs to that external ZIP and has SHA256
`6c48de584d279928599a9d38c86d1ce5cae9a692e64b3c5fb9dd8f52e28d38c5`.

The proposed baseline appends exactly those six complete, redacted native
records. All sixteen existing records retain their serialized bytes and order.
The resulting count is 22; no path-wide, rule-wide or content-wide exception is
introduced.

| Baseline | SHA256 |
| --- | --- |
| Original, 16 records | `605fb1f1823121075ceffc7ee1d352432f0cdf36a3f8470f7e3a9c41ddd2ab6a` |
| Proposed, 22 records | `c460c0623fe7c8acde749f134fc90564c22c387623be803763cd15e9bd848f91` |

## Six-record rationale

Every added record has rule `generic-api-key` and commit
`81bbfaa3ac63ae626476989135f5d17ee3b73654`, a two-parent historical merge.
Authenticated Git trees establish whole-file identity with baseline-associated
versions:

| Path | Lines | Existing baseline commit | Identical Git blob |
| --- | --- | --- | --- |
| `docs/audit/closure/KORPUS_v5_FINDINGS_CLOSURE.csv` | 62, 72 | `8282281cec9b58deb029b0123fd9b4e5f01c0cd1` | `9c9481223b40eee9c1595ef1cab9c5426aaa16d7` |
| `docs/audit/closure/KORPUS_v5_REMAINING_DEBT.csv` | 45, 52 | `8282281cec9b58deb029b0123fd9b4e5f01c0cd1` | `c718ef0f3e449850f01b57cf238bc9a714ebed8c` |
| `docs/audit/source/KORPUS_v4_REMEDIATION_BACKLOG_2026-08-01.csv` | 62, 72 | `0c04b9efef53f988056c4c9e2ed96afab4798bf9` | `66444c3fff19ee6166bb0113f60b216ddd8d2c5f` |

The [initial six-record decision](https://github.com/neuron7x/KORPUS/commit/699f5022ad253b23e3f1d1b956964d281b8da05b)
and [later historical reconciliation](https://github.com/neuron7x/KORPUS/commit/5cdc0da5ea2a9c233485f1d0274deb6bcbce880e)
describe these audit-document detections as false positives. That documented
history and the identical blobs support this specific proposed disposition;
neither creates standing authority to suppress future findings.

The pinned [Gitleaks baseline predicate](https://github.com/gitleaks/gitleaks/blob/83d9cd684c87d95d656c1458ef04895a7f1cbd8e/detect/baseline.go)
compares commit and authorship metadata as well as rule, location and entropy;
it explicitly omits the displayed fingerprint. The corrected merge-diff stream
therefore re-reports the existing material under different commit attribution.
Redacted field equality alone is not the material-identity proof. No credential
validity is inferred, and no secret or match contents are reproduced here.

## Performance and acceptance remain unresolved

The native run exited 1 after 230.407176 seconds with a context deadline: only
1,190 commits and 597,634,761 bytes were partially scanned. These six reports
are not a complete finding census. This proposal does not resolve that failure.

The 230-second native and 240-second parent bounds, full reachable-history
traversal and merge diffs, pinned tools and rules, redaction, ignore file,
baseline matcher, CPU/memory limits, isolation and cleanup requirements remain
unchanged. No history is rewritten. Independent review of this exact proposal,
fresh complete native execution within the original budget, and authenticated
evidence admission remain required.
