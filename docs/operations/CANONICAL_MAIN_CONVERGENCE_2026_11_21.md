# Canonical main convergence — 21 November 2026

This integration is tracked by issue #136. It imports an existing three-branch
source stack into the observed canonical main without deleting the source refs.
This document records source provenance and verification obligations; it does not
declare a production release or transfer historical test results to a new commit.

## Pinned source inputs

| Input | Commit |
| --- | --- |
| Observed main, including readiness repair #126 | `aa80bc59e4f6cb50d90d7de9d9569c0bf3994814` |
| Evaluation evidence #131 / closed-unmerged PR #134 | `91b1ab5750e04e846ccec31fe319a3b6235f3b14` |
| Extraction fidelity #132 / closed-unmerged PR #135 | `e410b48d4393707f9d1641c5f077351f1907f640` |
| Answer obligations #133, containing both preceding heads | `8e14ced4741ef19322dcc8325e9a36f70f00f991` |
| Stack/main merge base | `977e745a3b9af9f748e8bb78ad32782cb2e20d88` |

The stack has four commits absent from the observed main. It is imported once
through its final head, preserving both earlier heads through Git ancestry.
Eight other branches in the initial thirteen-branch census already belong to main;
their retained refs do not require a second source import.

## Conflict resolution

Only `SOURCE_MANIFEST.json`, `PACKAGE_BUILD.json` and
`config/operations/module-budget.json` conflict with this stack. Source/package
identities are regenerated from the combined staged source with the repository's
existing producers; neither side's stale digest is selected as current evidence.

Module budgets use a checked three-way union. Main's sole independently changed
entry, `scripts/ready_response_contract.py`, remains exact. The stack's disjoint
module entries and its existing `raised`/`lowered` records remain exact. A module
changed on both sides would require review rather than selecting a larger ceiling.
No global ceiling, original threshold, skip or timeout is weakened by integration.
Main's readiness implementation and its tests remain unchanged.

## Producer/consumer compatibility correction

PR #134's review identified that `remap_reference_versions.py` remapped expected
version UUIDs but retained the old `sampled_from_version`. The stricter reference
evaluator then correctly refused the producer's output. A neutral archive fixture
reproduced this failure before correction.

The producer now admits the frozen source set before database reads and remaps the
sampled holder through the same source-hash mapping as its expected holders. If
that sampled source cannot map, its case is explicitly recorded as dropped; an
alternative expected holder cannot silently replace the sampled evidence. Duplicate
mapped holders are collapsed. The new dataset gets its own digest and retains the
original dataset digest/path as provenance. The evaluator's admission invariant is
unchanged. Regression controls exercise real synthetic SQLite source/target maps,
missing sampled holders, aliased holders, preserved source bytes and rejected stale
source digests. M826 targets retention of the old sampled holder.

## Independent final-citation identity correction

A separate verifier reproduced two false admissions on the stack head using a
generic neutral archive question. Substituting only a citation's document or
version UUID left its actual quote/span intact, and the final answer still passed.
The grammar-empty early return skipped the existing source-identity check.

The final gate now runs that same document/version/span binding for every query,
including queries with no recognized subject or property obligation. Valid generic
answers retain their positive control. Two service-level fault injections require
an explicit refusal with no emitted claims or citations; M827 reinstates the early
return to test the causal guard. No new natural-language inference is claimed.

## Bounded single-letter name policy

The verifier also found that a trailing capital label `A` disappeared as the
function word `a`, and even a quoted `"A"` could borrow an ordinary source article
through case folding. Unquoted trailing capital single-letter function-word labels
now produce an explicit ambiguity refusal. A quoted single-letter function-word
name requires a quoted name in the source itself; an ordinary article cannot
satisfy it. English and Ukrainian controls preserve genuine quoted-name answers.
M828 and M829 target these two separate boundaries. This is a narrow conservative
grammar policy, not a claim that every possible natural-language name is resolved.

## PDF annotation appearance boundary

The independent parser review found real visible text in a PDF annotation's normal
appearance stream (`/Annots` → `/AP` → `/N`) that the page content extractor omitted.
The page had previously been accepted as blank or as containing only its native
header. Unsupported annotation appearances are now explicitly refused before a
successful page extraction, including when OCR is enabled. Neutral real-PDF direct
and worker controls retain annotation-free blank/native pages and reject the
overlay; M830 restores the omission. The existing M810 image/header mutation keeps
its original witness and meaning with its literal target updated for the equivalent
paint-set expression. This does not claim universal annotation or OCR semantics.

## Verification and remaining boundaries

The first native research-assurance run for PR #137 at
`8785535143cce79202f15279bd80d6b84f680f61` found a real regression: 29 of the
unchanged 30 frozen assurance cases passed. The `safe-source-after-injection`
case refused its valid access-control sentence because the noun-phrase grammar
misclassified the predicate `потрібен` as a literal subject and `контроль` as a
literal property. The existing predicate boundary recognized `потрібно` but omitted
the four agreement forms `потрібен`, `потрібна`, `потрібне` and `потрібні`.

Those four forms now use the existing predicate-question path. Explicit names,
quoted subjects and identifiers are still conjunctive obligations, and final
citation identity checks remain unconditional. Regression controls keep the frozen
safe sentence after the injected instruction while refusing missing explicit
subjects; M831 restores the observed masculine-form defect. The frozen dataset,
source fixtures, expected answers, thresholds and evaluation gate are unchanged.
The observed failure is recorded in
[research-assurance run 44872617873](https://github.com/neuron7x/KORPUS/actions/runs/44872617873/job/136750290714).

The subsequent native run for `0b4ef3374e43d0124dc6d921f33e284eb7ea58ad`
passed all 30 evaluation cases and killed all 700 then-registered mutants. Its
[PostgreSQL suite](https://github.com/neuron7x/KORPUS/actions/runs/44873328016/job/136752557488)
still found two real regressions. A valid effective-date procedure answer was
refused because `встановлює` did not delimit its subject/property head from its
predicate/value. That exact source predicate now uses the existing head-binding
contract; a foreign subject, a name appearing only after the predicate, and a
missing coordinated property remain refusals. M832 restores the omitted delimiter.
The unchanged temporal test still requires refusal before the effective date and
an answer on that date.

The same run found an import cycle through the retrieval facade. Evidence helpers
now import `normalize_text` and `tokenize` directly from their existing leaf module,
`retrieval_math`; the facade already re-exported those exact objects. No function
implementation, graph edge exclusion or acyclicity expectation is changed. Both
original failing tests remain unchanged. Downstream coverage, repository and package
jobs were skipped in that failed run and require fresh execution after this repair.

The integrated commit requires fresh focused regression, static-quality, registry
and source/package-identity checks, independent review, and the protected hosted
checks. Hosted PostgreSQL, mutation, Compose, package and other applicable checks
must identify the actual integrated commit; earlier green runs remain historical.

The local workspace's system Git binary lacks the root ownership required by
`trusted_system_tools.py`; the Git-aware manifest path correctly refuses there.
Derived identities are therefore generated only in the producer's supported
metadata-free archive mode: export the exact staged tree, check all blob bytes and
Git modes, run the unchanged producer, and import the two generated identity files.
This generation method is not a passed Git-authority, native mutation or hosted
admission gate. The ownership predicate remains unchanged.

PR #116 / issue #102 remains separate at
`edd159a02037c45e1abe3f5396c0757c14a51aa1`. Its
[source-security job](https://github.com/neuron7x/KORPUS/actions/runs/44656066746/job/136022464344)
failed at the unchanged native scanner deadline with a partial history scan;
hosted readback also failed. Those failures and conflicts are not bypassed here.
Neither this document nor a green
software workflow establishes real corpus recovery, hosted cryptographic signing,
production environment qualification or production admission. Those obligations
remain explicit under the existing coordinator #97 and their individual issues.
