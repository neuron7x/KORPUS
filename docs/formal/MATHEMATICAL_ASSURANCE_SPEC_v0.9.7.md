# KORPUS v0.9.7 Mathematical Assurance Specification

**Status:** executable mathematical contract for the v0.9.7 math-hardening milestone  
**Date:** 2026-08-24  
**Authority boundary:** this document specifies invariants and evidence requirements; it does not promote the repository to production by itself.

## 1. Scope

This specification governs the numeric and statistical surfaces that can alter retrieval, Predictive Evidence Control (PEC), Decision-Gradient Computing (DGC), calibration, TEVV evidence, risk thresholds, replay/oracle decisions, controller training/export, ablation, contextual benchmarks, and release evidence.

The target property is not “mathematically plausible”. The target is: **every decision-relevant numeric object has an explicit domain, invalid values fail closed, statistical claims expose assumptions, and the implemented predicates are executable and falsifiable.**

## 2. Primitive numeric domains

The implementation uses the following semantic domains at trust boundaries.

| Symbol | Domain | Executable predicate | Rejects |
|---|---|---|---|
| `N0` | non-negative integers | `strict_int(x) and x >= 0` | bool, strings, fractional floats, negatives |
| `N+` | positive integers | `strict_int(x) and x > 0` | zero and all invalid `N0` values |
| `R_f` | finite reals represented by Python `int|float` | `finite_number(x)` | `NaN`, `±Inf`, bool, strings, overflow-to-float |
| `P` | finite probabilities/rates | `R_f ∩ [0,1]` | out-of-range and non-finite values |
| `P°` | open probability interval | `R_f ∩ (0,1)` | 0, 1, invalid/non-finite values |
| `R+^d` | finite non-negative resource vector | each component `R_f` and `>=0`, same dimensionality | negative, NaN/Inf, empty/mismatched vectors |
| Bernoulli counts | `(k,n) ∈ N0², k≤n` | `_bernoulli_counts(k,n)` | bool/count coercion, `k>n` |

**Invariant MATH-DOM-001:** strings are not numbers at authority boundaries. JSON numeric fields must remain JSON numbers.  
**Invariant MATH-DOM-002:** Python booleans are not accepted as integers even though `bool` subclasses `int`.  
**Invariant MATH-DOM-003:** `NaN` and infinity never participate in thresholds, support bounds, replay measurements, resource comparisons, or controller admission.  
**Invariant MATH-DOM-004:** rank/count fields are integers; `1.5 -> 1` coercion is prohibited.

## 3. Statistical kernel

Canonical implementation: `apps/api/src/korpus/application/statistical_bounds.py`.

### 3.1 Wilson score interval

For `k` Bernoulli successes in `n>0` trials, `p̂=k/n`, and positive normal quantile `z`:

`den = 1 + z²/n`

`center = (p̂ + z²/(2n)) / den`

`spread = z * sqrt(p̂(1-p̂)/n + z²/(4n²)) / den`

`CI = [max(0, center-spread), min(1, center+spread)]`

For `n=0`, KORPUS returns `[0,1]` fail-closed rather than fabricating information.

Wilson is used as a finite-sample score interval for Bernoulli proportions. It is **not** described as an exact binomial interval.

### 3.2 Hoeffding one-sided upper bound

For empirical Bernoulli error rate `ê=k/n`, `n>0`, confidence failure probability `δ∈(0,1)`, and `H≥1` simultaneous hypotheses:

`δ_local = δ/H`

`r = sqrt( ln(1/δ_local) / (2n) )`

`upper = min(1, ê + r)`

For `n=0`, the upper error bound is `1.0`, therefore no leaf can gain low-risk authority without samples.

The `δ/H` term is a union-bound/Bonferroni correction. The bound is valid only under the assumptions required by the selected Hoeffding application; independence or an otherwise justified dependence model must not be silently inferred from row count.

### 3.3 Hoeffding two-sided interval

For empirical rate `p̂=k/n`:

`r = sqrt( ln(2/δ) / (2n) )`

`CI = [max(0,p̂-r), min(1,p̂+r)]`

For `n=0`, KORPUS returns `[0,1]`.

### 3.4 Provenance

- W. Hoeffding, *Probability Inequalities for Sums of Bounded Random Variables*, JASA 58(301), 1963, DOI `10.1080/01621459.1963.10500830`.
- NIST/SEMATECH binomial confidence-limit documentation gives the Wilson-derived score-limit formula and contrasts it with the simple normal approximation.

## 4. Retrieval mathematics

Canonical implementation: `retrieval_math.py`.

### 4.1 BM25 lexical component

For term frequency `f`, document length `|D|`, average document length `avgdl`, document frequency `df`, document count `N`, and parameters `k1,b`:

`IDF = ln(1 + (N-df+0.5)/(df+0.5))`

`term_score = IDF * f(k1+1) / ( f + k1(1-b+b|D|/avgdl) )`

Implemented parameter domains:

- `k1 ∈ [0.1,4.0]`
- `b ∈ [0,1]`

Reference model provenance: S. Robertson & H. Zaragoza, *The Probabilistic Relevance Framework: BM25 and Beyond*, DOI `10.1561/1500000019`.

### 4.2 Hybrid retrieval score

The final retrieval score is a convex weighted combination of normalized components:

`S = Σ_i w_i x_i`, with `w_i∈[0,1]`, `Σ_i w_i = 1`, and normalized component values constrained to `[0,1]`.

The hybrid score is an **engineering ranking score**, not a posterior probability. No downstream component may interpret `S=0.8` as “80% probability of correctness” without a separately validated calibration map.

### 4.3 Lexical normalization

BM25 lexical score `L≥0` is transformed as:

`L_norm = 1 - exp(-L/3)`

This is monotone and bounded in `[0,1)`. The divisor `3` is a system parameter, not a theorem; its empirical calibration remains a separate evidence obligation.

## 5. PEC/DGC decision mathematics

### 5.1 Decision sensitivity

Online PEC does not invent counterfactual worlds. Offline replay compares externally observable decisions for the same query under different retrieval actions.

For a candidate action over replay transitions:

`flip_rate = decision_flips / samples`

The uncertainty interval uses the canonical two-sided Hoeffding kernel. Zero samples produce `[0,1]`, not an apparent zero-risk estimate.

### 5.2 Decision value

Additional compute has decision value only if the candidate remains admissible and at least one is true:

1. safety is recovered;
2. quality is recovered;
3. the external decision changes.

A ranking change alone is not decision value.

### 5.3 Resource oracle

The PEC oracle uses vector partial order, not an invented scalar exchange rate.

For resource vectors `a,b ∈ R+^d`:

`a ≺ b` iff `∀i: a_i ≤ b_i` and `∃j: a_j < b_j`.

A unique non-dominated admissible action can be selected. If multiple Pareto minima are incomparable, the oracle returns `UNKNOWN/BASELINE`; it does not fabricate weights between latency, searches, planner calls, semantic calls, candidate count, tokens, and provider cost.

## 6. Controller training and admission

### 6.1 Data separation

Training, grouped validation, calibration, and replay evidence are separate roles. Controller authority is exported only from source-bound artifacts.

### 6.2 Leaf admission

A controller leaf is admitted only when both hold:

`calibration_samples >= minimum_leaf_samples`

`upper_error_bound <= controller_risk_limit`

All four operands are domain-checked before comparison. `minimum_leaf_samples ∈ N+`; `controller_risk_limit ∈ (0,1)`; sample/error counts are strict integers; upper error bound is finite in `[0,1]`.

### 6.3 Feature support

Numeric support bounds must be finite and ordered:

`minimum <= maximum`.

A non-finite feature cannot become “in support” through IEEE-754 comparison semantics. Calibration support construction raises on `NaN/Inf` instead of poisoning min/max state.

### 6.4 No semantic type coercion

Controller export rejects, rather than converts:

- `"false"` for a boolean;
- `"0.05"` for a numeric risk limit;
- `1.5` for a sample count/rank;
- `NaN/Inf` for scores, bounds, latency or resources.

## 7. Ablation and paired evidence

Ablation compares paired candidate/baseline rows with identical query sets.

Safety or quality regression forces `FAIL` before efficiency claims are considered. Resource superiority is evaluated on finite non-negative paired measurements. The directional win probability interval uses Wilson bounds over informative non-tied pairs.

`minimum_pairs` is a positive strict integer. If directional evidence is insufficient, status is `UNKNOWN`, not `PASS`.

## 8. Contextual retrieval benchmark

Contextual projections must preserve evidence and source binding. Required fields are exact booleans; gold ranks are positive integers. A baseline gold hit lost by the contextual projection is a failure condition.

No contextual text is promoted to evidence merely because it improves rank.

## 9. Human/TEVV evidence semantics

Human-judgment authority requires:

- actor type explicitly `HUMAN`;
- explicit boolean `model_self_judgment == false`;
- exact revision/profile/phase binding;
- valid SHA-256 provenance;
- complete expected cohort.

Missing or string-encoded self-judgment flags are invalid rather than defaulting into authority.

TEVV ledgers require strict booleans and non-negative integer failure counts before aggregates are recomputed.

## 10. Failure-memory table

| ID | Null attack / defect | Pre-hardening behavior | Required behavior |
|---|---|---|---|
| MATH-FM-001 | huge integer through `float()` | possible `OverflowError` | predicate returns false, no crash |
| MATH-FM-002 | `NaN` evidence score | could canonicalize to maximum score in `_round` | reject |
| MATH-FM-003 | `NaN/Inf` replay measurement | comparison could fail open | reject |
| MATH-FM-004 | fractional retrieved rank | `int(1.5) -> 1` | reject |
| MATH-FM-005 | string boolean | `bool("false") -> True` | reject |
| MATH-FM-006 | negative resource vector | Pareto relation over invalid cost | reject |
| MATH-FM-007 | `NaN` support bound | comparisons non-falsifiable | reject |
| MATH-FM-008 | `NaN` risk threshold | clamp/comparison semantics distort gate | reject before clamp |
| MATH-FM-009 | zero statistical samples | apparent low empirical error | return maximally uninformative bound |
| MATH-FM-010 | incomparable Pareto minima | arbitrary scalar winner | `UNKNOWN/BASELINE` |
| MATH-FM-011 | non-finite calibration feature | poisons min/max support | reject |
| MATH-FM-012 | invalid human self-judgment flag | missing/coerced flag can blur provenance | reject |

## 11. Executable evidence

The dedicated negative-control suite is `apps/api/tests/test_math_kernel_v097.py`.

The broader mathematical regression includes retrieval, PEC replay, DGC sensitivity, calibration, TEVV, risk, contextual benchmark, controller integration, human judgment, hosted evidence, and coverage-closure tests.

The mathematical gate is evidence of implementation consistency only. It is not evidence that real production samples are independent, representative, adversarially complete, or sufficient for a scientific/product claim.

## 12. Remaining falsification obligations

1. **Dependence structure:** demonstrate whether calibration/replay observations satisfy the independence assumptions used by the selected concentration bounds, or replace them with a dependence-aware procedure.
2. **Repeated queries / clustered users:** quantify effective sample size or group-level resampling when observations share query/user/source lineage.
3. **Multiple comparisons:** keep the tested hypothesis family explicit; union-bound `H` cannot be retrofitted after inspecting results.
4. **Retrieval score calibration:** validate any mapping from ranking scores to answer correctness separately; current hybrid score is not probabilistic.
5. **Distribution shift:** production/CANARY evidence must measure support drift and reject out-of-support controller use.
6. **External TEVV:** local deterministic tests cannot substitute for independent production-representative validation.
7. **Full repository regression:** the mathematical gate does not authorize a production release unless the complete repository gate and current-truth chain also close.

## 13. Promotion predicate

Mathematical assurance for this milestone is `PASS` only for the **targeted mathematical implementation surface** when:

`domain_negative_controls_pass`
`AND statistical_kernel_tests_pass`
`AND PEC/retrieval/calibration/TEVV targeted_regression_pass`
`AND source_manifest_verifies`.

Repository/production promotion remains separate and must fail closed if current-truth, full regression, mutation, external TEVV, production database/RLS, load/soak, signing, or provenance gates are not independently satisfied.
