# Assurance algebra v1

## Purpose

KORPUS separates *how mature the system appears* from *whether production promotion is authorized*. The first is a weighted engineering index. The second is a conjunction over exact, release-bound predicates. This prevents a strong UI score, high line coverage, or a large test count from numerically compensating for a missing security or provenance gate.

## Evidence partial order

An evidence point is:

`E = (class, source, release, status, executed, negative_control, independent, attested)`

Evidence classes are ordered:

`NONE < DECLARATIVE < STATIC < EXECUTED < EXECUTED_WITH_NEGATIVE_CONTROL < INDEPENDENT_ATTESTED`.

The order only applies **within the same `(source, release)` identity**. Evidence from another source tree is not “weaker”; it is about a different object and therefore incomparable. Joining incomparable evidence is forbidden.

### Conflict rule

For the same source/release identity, contradictory PASS/FAIL observations join to FAIL. Safety aggregation is monotone: adding contradictory evidence cannot improve a verdict.

## Engineering score

For dimension `i`, with normative policy weight `w_i`, observed score `s_i`, and evidence ceiling `c_i`:

`m_i = min(s_i, c_i)` when source/release identity matches and evidence status is PASS; otherwise `m_i = 0`.

`R = Σ w_i m_i`, with `Σ w_i = 1`.

The score is bounded in `[0,100]`. The executable reference implementation is `korpus.application.assurance_calculus` and its hypercube-bound test exhaustively checks every 0/100 corner of the configured dimension space used by the unit model.

## Evidence ceilings

The default v2 policy uses ceilings to prevent epistemic overstatement:

- non-executed evidence: at most 70;
- executed evidence without a negative control: at most 90;
- executed with negative control but without independent attestation: at most 97;
- independent attested evidence: up to 100.

These are **normative governance ceilings**, not empirically estimated probabilities.

## Production authorization

For mandatory gate set `G`, exact source digest `S`, and release `V`:

`AUTHORIZED = ∧_{g∈G} present(g) ∧ pass(g) ∧ source(g)=S ∧ release(g)=V ∧ class(g)≥required(g) ∧ external_properties(g)`.

There is no weighted fallback. One missing mandatory predicate yields false.

## Non-compensation theorem

Because `AUTHORIZED` is computed independently of `R`, for all maturity values `R ∈ [0,100]`, a missing mandatory gate implies `AUTHORIZED = false`. This is mechanically tested.

## Sensitivity

A dimension's maximum impact is exactly `100*w_i` percentage points. Sensitivity is therefore inspectable before a score is adopted; no hidden weight can dominate the index.

## Failure semantics

- missing evidence → zero contribution / blocking gate;
- stale source → zero contribution / blocking gate;
- wrong release → zero contribution / blocking gate;
- contradictory evidence → FAIL;
- self-attested external gate when independence is required → FAIL;
- unavailable tool → NOT_EXECUTED, never PASS.
