# KORPUS — Predictive Evidence Control
## Verified Research-to-Implementation Act · 2026-08-21

**Document class:** engineering implementation act / R&D-to-production protocol  
**Target baseline:** `KORPUS_v0.9.4_FULL_SSOT_CANONICAL_2026-08-21`  
**Purpose:** integrate predictive-processing / uncertainty / replay principles into KORPUS as a minimal, falsifiable, production-oriented retrieval-control mechanism.  
**Non-goal:** build a biologically realistic neural network, active-inference agent, EEG/fMRI subsystem, or online self-modifying model.

---

## 0. EXECUTIVE DECISION

Implement one bounded feature family named **Predictive Evidence Control (PEC)**.

PEC is not a new agent and not a new answer generator. It is a deterministic controller inserted between the first retrieval observation and any additional retrieval work.

The production rule is:

> **Spend additional retrieval / planning compute only when a content-addressed calibration profile predicts that the additional work is necessary to satisfy existing evidence constraints; otherwise stop. If the controller is stale, uncalibrated, out-of-support, or statistically underpowered, fall back to the current deterministic KORPUS path.**

The neuroscience transfer is functional, not metaphorical:

- **prediction:** estimate whether the next retrieval action will improve admissible evidence;
- **prediction error:** difference between offline-predicted benefit and counterfactually observed benefit;
- **precision:** finite-sample reliability of that estimate, represented by confidence/risk bounds rather than a free scalar;
- **replay:** offline re-execution of alternative retrieval actions on judged queries;
- **prioritization:** replay failures, controller–oracle disagreement, false accepts, false abstentions, and high residuals before routine cases;
- **plasticity:** proposals are offline, content-addressed, bounded, reviewed, and promoted separately; no online parameter mutation.

This maps directly onto KORPUS’s existing `calibration.py`, `risk.py`, `query_plan.py`, `retrieval.py`, `inference_budget.py`, and `plasticity.py`; no parallel cognitive subsystem is justified.

---

# 1. VERIFIED BASELINE — WHERE PEC ATTACHES

The current source already provides the required safety seams:

### 1.1 `application/calibration.py`
Current `CalibrationProfile` is content-addressed against dataset, system manifest and evaluation protocol. It already separates ranking validation from selective-answering validation and uses a finite-sample upper error bound. **Reuse this governance model; do not create an independent calibration authority.**

### 1.2 `application/query_plan.py`
The planner is correctly constrained to produce search strings, never answer text, and fails back to the original question. However, when a planner is configured, the current answer path invokes planning before knowing whether the original query already retrieves sufficient evidence. **This is the first concrete compute inefficiency PEC should remove.**

### 1.3 `application/retrieval.py` / `retrieval_math.py`
KORPUS already computes most of the cheap signals PEC needs: normalized retrieval score, lexical score, query coverage, character similarity, authority class, semantic score when enabled, temporal score, candidate count, MMR/diversity behavior. **Do not add an LLM to estimate uncertainty when observable retrieval-state features already exist.**

### 1.4 `application/risk.py`
Risk-adjusted thresholds already encode that operational/temporal/unclassified queries require stronger evidence. **PEC must consume risk class as a constraint; it must never lower these thresholds.**

### 1.5 `application/inference_budget.py`
A bounded loop already stops on fixpoint, evidence budget, conflict budget, or cycle budget. **PEC should select the next retrieval action inside this existing budget, not create a second loop.**

### 1.6 `application/plasticity.py`
Plasticity already produces deterministic, content-addressed proposals and prohibits automatic relaxation of safety thresholds. **PEC training/replay must follow the same proposal → validate → promote separation.**

---

# 2. EVIDENCE SYNTHESIS — WHAT THE RESEARCH ACTUALLY SUPPORTS

## 2.1 Neuroscience: predicted uncertainty should modulate processing, not become a decorative “brain score”

Frank et al., *Nature Neuroscience* 2026, directly recorded human hippocampus and visual cortex and found hippocampal ripple dynamics linked to predicted uncertainty and modulation of cortical prediction-error responses. The implementable principle is **expected information gain / uncertainty changes processing priority**; it is not evidence that software should imitate oscillations or ripples.

**KORPUS transformation:** use evidence-state uncertainty to decide whether more retrieval computation is warranted. Do not implement oscillatory dynamics.

## 2.2 Replay is constructive and compositional

He et al., *Nature Neuroscience* 2026, observed hippocampal replay reorganizing familiar building blocks into candidate sequences during compositional inference. Bakermans et al., *Nature Neuroscience* 2025, formalized reusable building blocks and replay-supported composition/generalization.

**KORPUS transformation:** replay should recombine controlled query primitives and rerun alternative retrieval actions offline; it should not regenerate facts or modify source evidence.

## 2.3 Replay should be prioritized by error / utility, not uniformly sampled

Mattar & Daw (2018) provide a normative “gain × need” account of prioritized replay. Schaul et al. (2015, DeepMind) show prioritized experience replay improves sample efficiency by replaying high-error transitions. Post-learning hippocampal–striatal work in *Nature Communications* 2025 reports replay biased toward reward-prediction-error signals and model improvements under RPE-prioritized replay.

**KORPUS transformation:** replay false accepts, false abstentions, controller–oracle disagreement, and high prediction residuals first. Do not spend equal calibration compute on already-stable cases.

## 2.4 Adaptive RAG research independently converges on query-specific retrieval decisions

ACL 2025’s broad comparison of **35 adaptive retrieval methods** `[ANCHORED — ACL 2025 benchmark; not transferable as a KORPUS performance claim]` found that uncertainty-estimation approaches can match more complex pipelines with better efficiency. EMNLP 2025 evaluated **27 external feature types** `[ANCHORED — EMNLP 2025 experimental design; not a required KORPUS feature count]` and showed LLM-independent adaptive retrieval can match complex LLM-based methods while improving efficiency.

**KORPUS transformation:** prefer cheap corpus/retrieval features over self-reported LLM confidence.

## 2.5 Query-adaptive hybrid retrieval has a direct implementation precedent

QuDAR (ACL 2026) adapts sparse-vs-dense retrieval and original-vs-expanded query weighting using query-specific confidence, including top-1/top-2 margin features. This is almost directly compatible with KORPUS’s lexical/semantic architecture.

**KORPUS transformation:** make planner/semantic escalation conditional on measured first-pass evidence state rather than static availability.

## 2.6 Model-internal confidence is not a safe primary control signal

QuCo-RAG (ACL 2026) explicitly motivates corpus-grounded uncertainty because model-internal logits/entropy may be badly calibrated. D²-RAG (ACL 2026) uses a lightweight retrieval-decision model with multidimensional uncertainty, but its generator-internal features are unnecessary for KORPUS’s extractive safety model.

**KORPUS transformation:** the primary PEC state is retrieval/corpus evidence, not the generator’s verbal confidence or entropy.

## 2.7 Adaptive test-time compute gives the right optimization template

Zhai et al. 2026 formalize per-instance compute allocation under a global budget with a **Solve-then-Learn** procedure: solve an offline constrained oracle per instance, then train a lightweight policy to imitate it. Their reported MATH improvement of up to **12.8% relative accuracy `[ANCHORED — paper-specific benchmark; explicitly non-transferable to KORPUS]`** is not the reason to adopt it; the useful contribution is the decomposition of global constrained inference into offline oracle decisions plus cheap online routing.

**KORPUS transformation:** enumerate retrieval actions offline, choose the cheapest action that passes evidence constraints, distill that decision into a small deterministic controller.

## 2.8 Risk must remain independently calibrated

C-RAG (ICML 2024) uses conformal risk analysis to certify RAG generation risk. Automatically Adaptive Conformal Risk Control (AISTATS 2025) develops input-adaptive risk control. KORPUS already has a finite-sample upper-bound gate.

**KORPUS transformation:** controller optimization is subordinate to risk admission. Never optimize a scalar “utility” that can trade safety for latency.

## 2.9 Contextual retrieval can attack the exact vocabulary-mismatch failure KORPUS already documents

Anthropic’s Contextual Retrieval engineering study reports a **49% reduction in top-20 retrieval failure `[ANCHORED — Anthropic internal benchmark, not a KORPUS expectation]`** for Contextual Embeddings + Contextual BM25 and **67% `[ANCHORED — same limitation]`** when adding reranking. Their core mechanism is to preserve document context in the retrieval representation.

**KORPUS transformation:** build a deterministic **retrieval-only contextual projection** from trusted metadata. Do not modify `span.text`, citation hashes, or source evidence. Do not initially generate context with an LLM.

## 2.10 Engineering methodology: simple primitives, test-first, independent verification

Boris Cherny’s Anthropic Claude Code engineering guidance recommends low-level composable tooling, test-first workflows, and separate verification contexts. Anthropic’s 2026 agent-eval guidance emphasizes explicit success criteria, groundedness, coverage and source quality. OpenAI’s 2026 evaluation guidance requires recording tested system, harness, budget and validity checks; OpenAI’s SWE evaluation audit estimated roughly **30% broken tasks `[ANCHORED — SWE-Bench Pro audit estimate; not a KORPUS dataset estimate]`**, which is a strong warning that evaluation data itself must be audited.

**KORPUS transformation:** implement PEC as small pure modules, write falsifiers before promotion, audit the benchmark before trusting benchmark gains.

---

# 3. SOURCE-SELECTION VERDICT

The source hierarchy for this implementation is:

1. peer-reviewed / archival neuroscience and ML papers with directly transferable mechanisms;
2. ACL/ICML/AISTATS empirical methods with reproducible evaluation definitions;
3. Anthropic/OpenAI engineering publications for harness/eval/production practice;
4. public frontier-lab model cards only for assurance methodology where relevant;
5. individual reputation is **not** an evidence class.

### Explicit exclusions

- **Ilya Sutskever / SSI:** no public 2025–2026 implementation paper was found that gives a superior adaptive-retrieval/control algorithm for this task. Do not cite his name as technical evidence.
- **Andrej Karpathy:** no directly relevant peer-reviewed adaptive-RAG/predictive-evidence algorithm was found. His minimalism and inspectability are useful engineering taste, not an academic dependency.
- **Dario Amodei:** Anthropic’s engineering work is relevant, but the mechanisms below are not attributed to Amodei personally unless he is an author.
- **xAI:** current public model/system cards are useful for evaluation/safety documentation but did not provide a retrieval-control mechanism superior to the ACL/ICML sources above. No xAI-specific subsystem should be added for prestige.

This exclusion is intentional: **celebrity is not provenance.**

---

# 4. TARGET ARCHITECTURE — MINIMAL DELTA

## 4.1 New primitive: `PredictiveEvidenceController`

Add one application-layer controller with no network access and no ability to generate answer content.

### Inputs

`EvidenceState` computed after a cheap first retrieval pass:

- `query_risk`
- `query_token_count`
- `candidate_count`
- `top1_score`
- `top1_top2_margin`
- `top1_query_coverage`
- `mean_topk_query_coverage`
- `score_concentration` or normalized score entropy
- `highest_authority_class`
- `top_authority_count`
- `evidence_redundancy`
- `original_query_has_eligible_evidence`
- `planner_already_used`
- `semantic_available`
- if semantic retrieval is admitted: sparse/dense overlap or rank-disagreement statistic
- current inference-budget state

All features must be deterministic functions of already-observed request/corpus/retrieval data.

### Explicitly forbidden controller inputs

- free-form LLM self-confidence;
- hidden-chain-of-thought text;
- unbound provider logits;
- user identity beyond policy/risk fields already required by authorization;
- data from an unverified external source;
- mutable global state not included in the profile/source identity.

## 4.2 Action set

Start with a small action grammar:

- `STOP_USE_CURRENT_EVIDENCE`
- `PLAN_QUERY_VARIANTS`
- `ENABLE_SEMANTIC_RETRIEVAL` — only if semantic retrieval is already admitted by profile and available
- `PLAN_AND_SEMANTIC`
- `ABSTAIN`

**Do not add candidate-budget expansion in the first implementation unless benchmark data proves planner/semantic routing is insufficient.** Current `plasticity.py` already governs global candidate-budget adaptation; per-query budget tuning would expand the interface surface and should earn its complexity empirically.

## 4.3 Correct control-flow change

Current conceptual flow:

`query → planner (if configured) → all searches → retrieval gates → answer/abstain`

Target flow:

`query → original-query retrieval → evidence state → PEC action → optional additional retrieval → evidence gates → answer/abstain`

This is the largest immediate efficiency win available without weakening evidence safety: easy queries stop before an LLM planner is called.

## 4.4 Runtime fallback

PEC is an optimization layer. Failure must preserve current behavior:

- missing profile → current deterministic baseline;
- profile digest mismatch → current deterministic baseline;
- state outside admitted support → current deterministic baseline;
- controller exception → current deterministic baseline + audit reason;
- controller requests unavailable semantic path → baseline or abstain according to existing dependency policy;
- controller may never turn an existing abstention into an answer by lowering evidence thresholds.

---

# 5. CONTEXTUAL BM25 — SAFE ADAPTATION OF CONTEXTUAL RETRIEVAL

Add a retrieval-only projection distinct from source evidence.

For each approved source span construct:

`retrieval_projection = trusted_document_context + original_span_text`

`trusted_document_context` may contain only deterministic trusted metadata already in KORPUS, for example:

- canonical document title;
- section heading;
- corpus subject / approved taxonomy labels;
- revision/effective-date descriptor where relevant;
- approved glossary aliases;
- document class / equipment / procedure identifiers.

### Hard invariant

`retrieval_projection != evidence_text`

The answer/citation layer must continue to use only `span.text`, `span_hash`, `quote_hash`, source revision and page/section provenance.

### Initial prohibition

Do **not** use an LLM to synthesize contextual prefixes in the first production iteration. Anthropic’s method is useful evidence that context helps retrieval, but generated context creates a new retrieval-poisoning channel in a controlled military corpus. First test deterministic metadata context. An LLM contextualizer becomes a later hypothesis only if deterministic context is insufficient and it passes an independent poisoning evaluation.

---

# 6. COUNTERFACTUAL REPLAY PROTOCOL

## 6.1 Replay unit

Each replay record is content-addressed and contains:

- query id / hash;
- corpus release digest;
- evaluation-protocol digest;
- risk class;
- baseline `EvidenceState`;
- action executed;
- retrieved span ids + ranks;
- final answer status;
- gold/reviewer judgment;
- retrieval quality measures;
- latency measured using monotonic high-resolution clock;
- search count;
- planner calls;
- semantic calls;
- candidate count;
- evidence/claim fingerprints.

## 6.2 Counterfactual enumeration

For every judged query, execute every action that is legally available for that query/corpus state. This creates observed action outcomes rather than synthetic reward labels.

No action is evaluated against a different corpus release, policy profile or evaluation protocol.

## 6.3 Oracle decision

Do **not** define a weighted utility such as:

`quality - α*latency - β*cost`.

There is no evidence-derived α or β.

Use constrained optimization:

1. eliminate actions that violate authorization or evidence invariants;
2. eliminate actions whose accepted-answer risk fails the existing finite-sample admission rule;
3. eliminate actions that degrade locked retrieval/answer quality relative to the safe reference policy under the preregistered statistical comparison;
4. among remaining actions select the measured least-cost action;
5. if no action is admissible, oracle action is `ABSTAIN` or safe baseline, according to current KORPUS semantics.

Cost is measured in real units, not an invented score: wall-clock latency, external-model calls, tokens sent externally, number of searches/candidates, and provider monetary cost when applicable.

## 6.4 Prediction error

For action `a` and state `x`:

`prediction_error = observed_action_value(x,a) - predicted_action_value(x,a)`

In the first release, the controller does not need a continuous neural value function. The implementation can define error as controller–oracle regret plus individual observable deltas:

- wrong action classification;
- additional cost relative to oracle;
- retrieval-quality delta relative to oracle;
- false accept;
- false abstention.

This keeps prediction error directly auditable.

## 6.5 Replay priority

Use lexicographic priority, not a weighted dopamine-like scalar:

1. safety / authorization violation;
2. accepted-answer error;
3. incorrect abstention where an admitted action existed;
4. controller–oracle disagreement;
5. largest measured retrieval-benefit residual;
6. novel/out-of-support state;
7. routine stable examples.

This captures the scientifically useful part of error-prioritized replay without importing biological decoration.

---

# 7. SOLVE-THEN-LEARN CONTROLLER TRAINING

## 7.1 Offline solve

`run_counterfactual_replay.py` generates the full action table and oracle label for each judged query.

## 7.2 Lightweight learning

Use an **offline-only interpretable classifier** to predict oracle action from cheap `EvidenceState` features.

Recommended first candidate: shallow decision tree / rule tree because it can be exported to deterministic JSON and evaluated in production without a runtime ML dependency.

`scikit-learn` may be used only in an optional calibration/dev environment. Its exact version is **UNKNOWN until dependency review and lock update**. Production `korpus-api` must not require scikit-learn.

Hyperparameters are **UNKNOWN** and must be selected by nested/group-aware validation; do not hard-code depth, leaf count or confidence cutoffs from literature.

## 7.3 Production representation

Export a canonical JSON profile containing:

- schema version;
- source/dataset/protocol digests;
- ordered feature schema;
- normalization/bins if any;
- deterministic rule tree;
- action vocabulary;
- leaf calibration evidence;
- per-leaf admission status;
- global fallback action;
- training/replay receipt digest.

Runtime evaluator is pure Python and deterministic.

## 7.4 Out-of-support behavior

A leaf/state without sufficient calibration is not “low confidence”; it is **not admitted**. Runtime immediately uses the existing safe baseline. This is the software analogue of precision weighting: weak evidence cannot exert strong control.

---

# 8. STATISTICAL / EVALUATION PROTOCOL

## 8.1 Dataset construction

Build a judged query set from real KORPUS tasks and documented retrieval failures. Include:

- successful ordinary queries;
- vocabulary-mismatch queries;
- rare technical identifiers;
- temporal questions;
- operational/high-risk questions;
- ambiguous questions;
- contradictory-source cases;
- no-answer cases;
- adversarial query-plan/control-injection cases;
- queries where semantic retrieval helps;
- queries where semantic retrieval introduces noise.

### Leakage control

Partition/group by source document / release lineage so near-duplicate passages from one source cannot sit in both training and locked evaluation partitions.

Do not optimize against the final locked evaluation set.

## 8.2 Evaluation-data audit

Before model/controller evaluation:

- validate every gold span still exists in the tested corpus release;
- validate answerability labels;
- validate no stale revisions;
- validate task instructions against production behavior;
- flag ambiguous/multi-answer cases;
- perform independent review on disputed cases;
- record exclusions with reasons.

This is mandatory because benchmark defects can dominate measured progress; OpenAI’s 2026 SWE-Bench Pro audit estimated about **30% problematic tasks `[ANCHORED — specific external benchmark estimate; not a KORPUS estimate]`**.

## 8.3 Metrics

### Retrieval quality

- `Recall@k`
- `nDCG@k`
- `MRR@k`
- gold-span hit rate
- authority-correct retrieval rate

`k` values are **UNKNOWN until the existing KORPUS evaluation protocol is reconciled with runtime answer limits**; do not import top-k values from external papers.

### Answer/selective quality

- accepted-answer error rate;
- answer coverage rate;
- false-accept count;
- false-abstention count;
- contradiction/review escalation rate;
- evidence/query coverage;
- citation/source integrity.

### Efficiency

- end-to-end latency distribution;
- planner-call rate;
- semantic-call rate;
- searches per query;
- candidates scored per query;
- external tokens per query;
- measured provider cost per query when applicable.

## 8.4 Promotion predicates

The new system promotes only if all predicates hold on the locked evaluation protocol:

### Safety

- accepted-answer finite-sample upper risk bound does not exceed the deployed risk limit;
- no authorization/scope invariant regression;
- no new unsourced-claim path;
- no threshold relaxation by controller.

### Quality non-inferiority

- paired confidence interval for retrieval-quality delta does not support degradation relative to baseline;
- paired confidence interval for answer-coverage delta does not support degradation relative to baseline;
- high-risk strata are evaluated separately rather than hidden in global averages.

### Efficiency superiority

At least one resource dimension must have a confidence-supported improvement while safety/quality predicates remain satisfied. Otherwise PEC has added complexity without value and must be rejected.

### Determinism

Same query + identity + corpus release + controller profile + calibration profile must yield the same action trace.

---

# 9. REQUIRED ABLATIONS

Run the following systems on exactly the same locked tasks and corpus release:

- current KORPUS baseline;
- baseline with planner invoked only after first-pass failure;
- deterministic contextual BM25 projection only;
- PEC without contextual projection;
- PEC + contextual projection;
- PEC + semantic retrieval only when semantic index/profile is admitted.

The purpose is causal attribution. If “full system” wins but PEC alone adds nothing, PEC does not earn its complexity.

Do not compare configurations using different query sets, corpus releases, provider models or time budgets.

---

# 10. METAMORPHIC / COMPOSITIONAL REPLAY

Use controlled transformations as the engineering analogue of compositional replay.

Transformations must preserve task semantics and be independently validated:

- approved synonym substitution;
- Ukrainian inflection/morphology variants;
- abbreviation ↔ expanded term;
- equipment identifier formatting variants;
- word-order changes that preserve meaning;
- approved military ↔ civilian terminology aliases where doctrine permits the equivalence;
- removal/addition of non-semantic politeness framing.

### Metamorphic invariants

For a semantics-preserving transform `T(q)`:

- authorization decision unchanged;
- risk class should not become weaker without an explicit rule reason;
- evidence authority class must not degrade;
- gold evidence must remain retrievable or failure is recorded;
- answer must not move from abstain/review to answered merely because a planner generated a more permissive phrasing;
- citations must remain source-bound.

Generated transformations never become production facts or training labels without validation.

---

# 11. EXACT CODE DELTA

## 11.1 New application modules

### `apps/api/src/korpus/application/evidence_state.py`
Responsibilities:

- immutable `EvidenceState`;
- deterministic feature extraction from query/risk/retrieved evidence;
- no model/network calls;
- canonical serialization/fingerprint.

### `apps/api/src/korpus/application/predictive_evidence_control.py`
Responsibilities:

- `RetrievalAction` enum;
- pure controller evaluator;
- profile binding checks;
- out-of-support fallback;
- action trace structure;
- no answer generation.

### `apps/api/src/korpus/application/controller_profile.py`
Responsibilities:

- Pydantic schema for exported controller;
- digest validation;
- bindings to corpus/system/evaluation protocol;
- admitted/unadmitted leaves;
- explicit fallback semantics.

### `apps/api/src/korpus/application/contextual_projection.py`
Responsibilities:

- deterministic trusted-metadata projection;
- strict separation between retrieval projection and evidence text;
- projection hash/version.

## 11.2 Modify existing modules

### `answer_query.py`
Replace “planner first” with:

1. original-query retrieval;
2. evidence-state computation;
3. controller decision;
4. optional planner/semantic action;
5. merge evidence;
6. existing eligibility/support/contradiction path unchanged.

### `query_plan.py`
Keep planner admission rules unchanged. Expose planning as an explicitly requested action rather than an unconditional configured step.

### `retrieval.py`
Expose enough component observations to build `EvidenceState`; do not change authority lexicographic ordering.

### `calibration.py`
Add controller-profile binding/status; do not silently merge controller calibration with answer-risk calibration.

### `inference_budget.py`
Record action cycles and stop on unchanged decision/evidence as today. PEC may select the next action, but budget remains sovereign.

### `plasticity.py`
Allow replay/controller metrics to generate a proposal artifact. Keep automatic safety relaxation prohibited.

## 11.3 Offline scripts

- `scripts/build_pec_eval_dataset.py`
- `scripts/audit_pec_eval_dataset.py`
- `scripts/run_counterfactual_replay.py`
- `scripts/solve_pec_oracle.py`
- `scripts/train_pec_controller.py`
- `scripts/export_pec_controller.py`
- `scripts/verify_pec_controller.py`
- `scripts/run_pec_ablation_campaign.py`
- `scripts/run_pec_metamorphic_campaign.py`
- `scripts/promote_pec_profile.py`

Every script must emit content-addressed JSON receipts and non-zero exit on UNKNOWN/FAIL when used as a release gate.

---

# 12. TEST / FALSIFICATION CONTRACT

## 12.1 Unit tests

Add dedicated tests for:

- deterministic state fingerprints;
- margin/entropy edge cases;
- empty retrieval;
- one-candidate retrieval;
- planner unavailable;
- semantic unavailable;
- profile digest mismatch;
- stale corpus release;
- state outside admitted leaf;
- risk-class preservation;
- no safety-threshold relaxation;
- contextual projection cannot alter evidence text/hash;
- identical state/profile gives identical action.

## 12.2 Integration tests

Required end-to-end cases:

- easy query never calls planner;
- lexical failure triggers planner only when admitted;
- planner failure returns baseline semantics;
- semantic escalation occurs only when profile and egress/dependency policy permit it;
- no additional retrieval after sufficient evidence;
- controller failure cannot create an answer that baseline would abstain from because of insufficient evidence;
- controller trace reaches answer audit.

## 12.3 Negative controls / mutants

The mutation catalogue must explicitly contain falsifiers that:

- force `STOP` for every state;
- force expensive escalation for every state;
- ignore risk class;
- accept stale controller profile;
- bypass profile digest binding;
- treat an unadmitted leaf as admitted;
- allow online self-promotion;
- use free-form LLM confidence as a trusted feature;
- contaminate source `span.text` with contextual projection;
- remove original-query-first invariant;
- let number of planner variants boost relevance;
- drop action-trace audit evidence;
- permit controller to lower answer thresholds.

A mechanism without a mutant/negative control demonstrating that its invariant can fail is not accepted.

---

# 13. OBSERVABILITY

Add metrics with low-cardinality labels only:

- PEC action counts;
- fallback reasons;
- planner avoided/executed;
- semantic avoided/executed;
- first-pass sufficiency rate;
- out-of-support rate;
- controller profile id/digest exposed through readiness metadata, not high-cardinality metric labels;
- latency by action class;
- false-accept/false-abstention metrics only from judged evaluation/offline review, never inferred from production model confidence.

Audit record must contain:

- controller profile digest;
- state fingerprint;
- selected action(s);
- fallback reason;
- planner use;
- semantic use;
- final evidence fingerprints;
- corpus release and calibration profile.

---

# 14. RELEASE / ROLLOUT PROTOCOL

## Phase A — shadow only

PEC computes actions but production executes the current baseline path. Compare predicted action and counterfactual baseline outcome. No user-visible behavior change.

## Phase B — canary

PEC executes only for query strata whose controller leaves are admitted by the calibration protocol. Any unknown leaf/state uses baseline.

## Phase C — governed promotion

Promote only a content-addressed controller profile that passes:

- dataset audit;
- counterfactual replay;
- locked evaluation;
- ablations;
- metamorphic tests;
- full regression;
- mutation campaign;
- existing KORPUS current-truth/release gates.

### Rollback

Rollback is profile-level: remove/disable PEC profile and return to baseline behavior without schema/data rollback. This must be executable without rebuilding source code.

---

# 15. WHAT MUST NOT BE IMPLEMENTED

The following are rejected unless future evidence changes the decision:

- predictive-coding neural network in KORPUS core;
- free-energy / active-inference scalar objective;
- dopamine/acetylcholine-inspired arbitrary coefficients;
- EEG/MEG/fMRI foundation model dependency;
- online reinforcement learning on production users;
- online mutation of answer-risk thresholds;
- planner-generated facts;
- LLM self-confidence as primary retrieval trigger;
- generative contextual text mixed into source evidence;
- large agent framework around the controller;
- scalar utility that allows latency savings to compensate for increased answer risk.

These either fail causal relevance to the present bottleneck or violate KORPUS’s evidence-governance model.

---

# 16. ENGINEERING EXECUTION ORDER

The engineering department should execute the work in this dependency order:

1. freeze existing canonical SSOT and source digest;
2. write PEC invariants and negative controls before implementation;
3. implement `EvidenceState` only;
4. instrument baseline first-pass retrieval and collect state features;
5. build and audit judged evaluation dataset;
6. implement deterministic contextual projection and benchmark it independently;
7. implement counterfactual replay runner;
8. solve offline oracle actions;
9. implement/export controller profile;
10. integrate PEC decision seam into `answer_query.py` without changing downstream evidence gates;
11. run targeted unit/integration/falsification tests;
12. run ablations and metamorphic campaign;
13. run full existing KORPUS mutation + regression + assurance gates;
14. shadow deployment;
15. compare shadow actions against adjudicated production samples;
16. canary only admitted states;
17. promote content-addressed profile or reject PEC if efficiency superiority is not demonstrated.

The system must remain useful after every step; no “big-bang neuroarchitecture” branch is permitted.

---

# 17. ACCEPTANCE CRITERIA — FINAL PRODUCT SEMANTICS

PEC is considered implemented only when all of the following are true:

- runtime can answer the same query without invoking planner/semantic work when first-pass evidence is sufficient;
- controller is deterministic and source/profile bound;
- unknown/stale/unadmitted controller state fails back to current safe behavior;
- existing authority, authorization, contradiction, citation and extractive-support semantics are unchanged;
- counterfactual replay can reproduce every promoted controller decision from immutable artifacts;
- evaluation dataset has an explicit audit receipt;
- no statistically supported degradation exists on locked safety/quality metrics;
- at least one measured compute/cost/latency dimension improves with uncertainty bounds supporting the improvement;
- controller is independently killable by negative controls/mutation tests;
- full KORPUS release gates pass on the final source digest;
- removing the controller profile restores baseline semantics without data migration.

If efficiency does not improve while quality is preserved, **PEC FAILS and is removed**. Neuroscience inspiration does not grant architectural survival.

---

# 18. CORE BIBLIOGRAPHY

## Neuroscience / computational neuroscience

1. Frank, D. et al. **Human hippocampal ripples tune cortical responses based on predicted uncertainty.** *Nature Neuroscience* (2026). DOI: `10.1038/s41593-026-02345-6`.
2. He, L. et al. **Human hippocampal ripples coordinate planning sequences and compositional representations in neocortex.** *Nature Neuroscience* (2026). DOI: `10.1038/s41593-026-02291-3`.
3. Bakermans, J. J. W. et al. **Constructing future behavior in the hippocampal formation through composition and replay.** *Nature Neuroscience* 28 (2025).
4. Mattar, M. G. & Daw, N. D. **Prioritized memory access explains planning and hippocampal replay.** *Nature Neuroscience* 21 (2018).
5. Schaul, T., Quan, J., Antonoglou, I. & Silver, D. **Prioritized Experience Replay.** arXiv:`1511.05952` (DeepMind).
6. **Post-learning replay of hippocampal-striatal activity is biased by reward-prediction signals.** *Nature Communications* (2025).

## Adaptive retrieval / RAG

7. Moskvoretskii, V. et al. **Adaptive Retrieval Without Self-Knowledge? Bringing Uncertainty Back Home.** ACL 2025. DOI: `10.18653/v1/2025.acl-long.319`.
8. Marina, M. et al. **LLM-Independent Adaptive RAG: Let the Question Speak for Itself.** EMNLP 2025. DOI: `10.18653/v1/2025.emnlp-main.439`.
9. Kim, J. et al. **QuDAR: Query-Wise Dual-Perspective Adaptive Retrieval.** ACL 2026. DOI: `10.18653/v1/2026.acl-long.1791`.
10. Zhang, J. et al. **D²-RAG: Dual-Decision Retrieval-Augmented Generation via Multi-Dimensional Uncertainty and Utility-Aware Decoding.** Findings ACL 2026. DOI: `10.18653/v1/2026.findings-acl.754`.
11. Min, D. et al. **QuCo-RAG: Quantifying Uncertainty from the Pre-training Corpus for Dynamic Retrieval-Augmented Generation.** Findings ACL 2026. DOI: `10.18653/v1/2026.findings-acl.812`.
12. Xu, R. et al. **RAG in the Wild: On the (In)effectiveness of LLMs with Mixture-of-Knowledge Retrieval Augmentation.** Findings ACL 2026. DOI: `10.18653/v1/2026.findings-acl.849`.
13. Anthropic. **Introducing Contextual Retrieval.** Engineering publication (2024). Vendor benchmark; use as engineering evidence, not a transferable KORPUS performance guarantee.

## Risk / selective prediction / compute allocation

14. Kang, M., Gürel, N. M., Yu, N., Song, D. & Li, B. **C-RAG: Certified Generation Risks for Retrieval-Augmented Language Models.** ICML 2024, PMLR 235.
15. Blot, V., Angelopoulos, A. N., Jordan, M. & Brunel, N. J.-B. **Automatically Adaptive Conformal Risk Control.** AISTATS 2025, PMLR 258.
16. Zhai, Z. et al. **Adaptive Test-Time Compute Allocation for Reasoning LLMs via Constrained Policy Optimization.** arXiv:`2604.14853` (2026).
17. Ong, I. et al. **RouteLLM: Learning to Route LLMs with Preference Data.** arXiv:`2406.18665` (2024). Relevant for cost/quality routing; not adopted as runtime architecture.
18. Raposo, D. et al. **Mixture-of-Depths: Dynamically allocating compute in transformer-based language models.** arXiv:`2404.02258` (2024). Relevant principle: fixed total budget with context-sensitive allocation; not a KORPUS model-training proposal.

## Engineering / evaluation methodology

19. Anthropic. **Building Effective Agents.** Engineering publication (2024): simple, composable patterns over framework complexity.
20. Anthropic. **Effective Context Engineering for AI Agents.** Engineering publication (2025): context as a finite resource; optimize high-signal context.
21. Anthropic. **Demystifying Evals for AI Agents.** Engineering publication (2026): groundedness, coverage, source-quality and regression/quality suites.
22. Cherny, B. / Anthropic. **Claude Code: Best Practices for Agentic Coding.** Engineering publication (2025): explore/plan/code, test-first, independent verifier, isolated execution.
23. OpenAI. **Separating signal from noise in coding evaluations.** Research publication (2026): evaluation-task auditing and broken-task detection.
24. OpenAI. **A shared playbook for trustworthy third party evaluations.** Safety/evaluation publication (2026): system, harness, budget, elicitation, and validity-check reporting.
25. OpenAI. **Inside OpenAI’s in-house data agent.** Engineering publication (2026): golden task sets, executable outcome comparison and continuous regression evals.

---

# 19. FINAL RESEARCH VERDICT

The highest-value innovation is not “brain-inspired RAG”. It is a **governed, evidence-native adaptive compute controller** whose conceptual ancestry is consistent across neuroscience, information retrieval, selective prediction and frontier engineering practice.

Its distinguishing property for KORPUS is:

> **The system predicts whether another retrieval operation is worth executing, but the prediction has no authority to relax truth constraints. Uncertain controller states receive less control, not more confidence. Every promoted action policy is learned from counterfactual replay, bound to exact corpus/protocol digests, independently falsifiable, and removable without changing the evidence layer.**

That is the implementation target.

**Research eval-gate: PASS_WITH_CAVEATS.**

- **PASS:** causal mechanism, compatible architecture seam, independent RAG evidence, neuroscience anchor, statistical admission method, engineering protocol and explicit falsifiers exist.
- **CAVEAT:** numerical controller thresholds, tree complexity, action priors and expected KORPUS performance are **UNKNOWN** until the judged KORPUS replay dataset is built and the preregistered evaluation is executed.
- **FAIL condition:** if locked evaluation cannot show compute/latency/cost improvement without safety/quality degradation, remove PEC rather than preserving it for conceptual elegance.
