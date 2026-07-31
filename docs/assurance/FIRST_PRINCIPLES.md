# KORPUS first-principles value function

## Object of optimization

KORPUS is not optimized for answer rate, fluency, benchmark prestige, or model size.
It is optimized for **decision-useful, authorized, temporally valid, reproducible evidence delivery**.

For an evaluation set `Q`, the operational value is:

```text
V(Q) = U_supported
     - λu · N_unsupported
     - λl · N_access_leaks
     - λs · N_stale_authority
     - λc · N_bad_citations
     - λa · N_unreconstructable_actions
     - C_latency
     - C_human_review
```

This is a specification, not a fitted empirical equation. The loss weights are governance decisions. In controlled deployments, the following are hard constraints rather than tradeable penalties:

```text
N_access_leaks = 0
N_unsupported_critical_claims = 0
N_stale_authority_for_current_queries = 0
N_untraceable_answers = 0
```

Any optimization that improves answer rate while violating a hard constraint is rejected.

## Primitive objects

1. `Identity`: server-verified subject, roles, clearance, assigned corpora.
2. `Document`: authority and access envelope.
3. `DocumentVersion`: immutable source bytes, temporal validity, review state, supersession edge.
4. `EvidenceSpan`: immutable text and content hash.
5. `Claim`: exact extractive statement bound to one or more spans.
6. `Citation`: exact offsets, quote hash, source hash and version identifier.
7. `Decision`: answer or named abstention reason under a versioned calibration profile.
8. `AuditEvent`: ordered action record committed with an external-anchor outbox.

## Invariants that can fail

- `I-ACCESS-PRE`: inaccessible text never enters candidate memory, ranking, answer, citation, log, metric, or release hash.
- `I-TEMPORAL`: a superseded or rescinded version cannot answer outside its valid interval.
- `I-EVIDENCE`: every emitted claim equals a cited substring and its quote hash verifies.
- `I-ABSTAIN`: missing, contradictory, uncalibrated, or instruction-contaminated evidence produces a named refusal.
- `I-ATOMIC`: document metadata, version, spans and audit event commit or roll back together.
- `I-AUDIT`: audit sequence, predecessor relation, HMAC, database head and external anchor all agree.
- `I-REPRO`: fixed code, corpus release, calibration and query produce the same semantic answer.
- `I-BOUND`: candidate generation is bounded before reranking; no request performs an unbounded corpus scan.

## Six gates

1. Intuition: state the proposed mechanism and expected value.
2. Proof obligation: encode a falsifiable invariant or measurable hypothesis.
3. Null attack: introduce adversarial, irrelevant, stale, inaccessible and contradictory inputs.
4. Repetition: rerun with fixed seeds, permutations, concurrency and clean environments.
5. Consequence: block merge or deployment when the predicate fails.
6. Memory of ruins: retain killed mutants, failed hypotheses and incident evidence.

## Explicit non-goals

- An LLM is not an authority source.
- Retrieval score is not factual probability.
- Passing unit tests is not security authorization.
- High statement coverage is not assurance.
- Agent-generated code is not independently verified evidence.
