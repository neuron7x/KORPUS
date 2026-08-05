# Canonical data model

## Principal entities

`Document` identifies a logical work. `DocumentVersion` is immutable and contains a
hash, source, dates, rights basis, authority, validity and access tier. `Artifact`
points to the original or derived object. `Chunk` identifies an immutable evidence
span. `Embedding` is replaceable and versioned independently.

`Corpus` groups approved versions under a policy. `Review` records a reviewer,
decision, rationale and signed timestamps. `Supersession` creates a directed graph
between versions.

`Query`, `RetrievalRun`, `EvidenceSet`, `Answer`, `Claim`, and `Citation` form a
traceable answer chain. `PromptVersion`, `ModelRun`, and `PolicyDecision` support
reproducibility without storing unnecessary personal data.

`Course`, `Competency`, `Lesson`, `Assessment`, `QuestionVersion`, `Attempt`, and
`ReviewerDecision` support learning. Passing an assessment is not certification.

`Template`, `TemplateVersion`, `Draft`, and `ValidationResult` support documents.

## Validity boundaries

Three date fields decide whether a version governs an answer asked on a given day,
and each closes on a different side. Stating this here is not documentation for its
own sake: on 2026-08-03 a mutation flipping the `effective_until` comparison survived
the entire suite, because nothing in the tree said which side the boundary belonged to.

- `effective_from` — **inclusive**. A document takes effect on the day it names.
- `effective_until` — **inclusive**. Ukrainian normative practice reads «чинний до
  31 грудня» as valid through the 31st, so a version whose `effective_until` is today
  still governs today's answer and stops governing tomorrow.
- `rescinded_at` — **exclusive**, and it is a timestamp rather than a date. Rescission
  is an act, not a term: from the day it happens, the version no longer governs.

`is_valid_on` implements exactly this and `test_validity_boundaries.py` fails if any
of the three shifts by one day in either direction.

## Required invariants

- a chunk belongs to exactly one immutable document version;
- approved versions cannot be mutated, only superseded or revoked;
- an answer citation targets a chunk, never a mutable filename;
- a restricted chunk cannot appear in a lower-tier evidence set;
- deletion revokes retrieval immediately while preserving minimal audit proof;
- raw user identifiers are not sent to a model provider.

