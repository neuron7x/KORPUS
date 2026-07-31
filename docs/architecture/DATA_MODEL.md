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

## Required invariants

- a chunk belongs to exactly one immutable document version;
- approved versions cannot be mutated, only superseded or revoked;
- an answer citation targets a chunk, never a mutable filename;
- a restricted chunk cannot appear in a lower-tier evidence set;
- deletion revokes retrieval immediately while preserving minimal audit proof;
- raw user identifiers are not sent to a model provider.

