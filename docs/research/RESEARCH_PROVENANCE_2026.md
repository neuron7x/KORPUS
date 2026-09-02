# Research provenance and design consequences

This is a historical design-consequence record. The complete canonical bibliography is
`config/assurance/ASSURANCE_SOURCE_REGISTRY_2026.json`, rendered at
`docs/research/BIBLIOGRAPHY_2026.md`.

Reviewed: 2026-08-01. Sources below are primary research papers or first-party research/engineering publications. Authority is not inherited from institution names; every adopted idea is mapped to an executable design consequence.

## Stanford CRFM — HELM and AIR-Bench

Source: https://crfm.stanford.edu/2022/11/17/helm.html

Adopted consequence:

- evaluate across a taxonomy rather than one accuracy score;
- expose missing scenarios and metrics;
- standardize adaptation and record raw outputs;
- measure robustness, calibration, efficiency and harms in the same deployment context.

KORPUS implementation: risk-tagged frozen cases, separate leakage/citation/determinism metrics, explicit open obligations, reproducible dataset hash.

## Google DeepMind — FACTS, frontier and cyber evaluations

Sources:

- https://deepmind.google/research/evals/
- https://deepmind.google/blog/facts-grounding-a-new-benchmark-for-evaluating-the-factuality-of-large-language-models/
- https://deepmind.google/blog/strengthening-our-frontier-safety-framework/
- https://deepmind.google/blog/evaluating-potential-cybersecurity-threats-of-advanced-ai/

Adopted consequence:

- grounding is evaluated as complete support by supplied documents, not mere citation presence;
- safety gates use explicit capability/risk thresholds and early-warning tests;
- cyber evaluation must cover an end-to-end attack chain, not isolated trivia.

KORPUS implementation: claim-to-span checks, abstention, source/query injection cases, noninterference, attack-oriented mutation tests, named deployment blockers.

## xAI — blind production evaluation and atomic factual claims

Source: https://x.ai/news/grok-4-1

Adopted consequence:

- supplement public benchmarks with blind production-distribution evaluation;
- decompose factuality into atomic claims rather than judge only whole-answer style.

KORPUS implementation: claims are first-class schema objects; production evaluation is designed as a separate corpus-specific gate, not inferred from synthetic fixtures.

## RAGChecker

Paper: https://arxiv.org/abs/2408.08067

Adopted consequence: retrieval and generation failures require separate diagnostics. KORPUS records retrieved count, eligible count, retrieval components, evidence coverage, citation count and decision reason rather than one opaque score.

## ALCE

Paper: https://arxiv.org/abs/2305.14627

Adopted consequence: citation correctness and citation completeness are distinct. KORPUS verifies exact quote binding and measures query-token evidence coverage separately.

## Uncertainty-aware abstention

Paper: https://arxiv.org/abs/2607.04430

Adopted consequence: a threshold is not valid because it “looks reasonable.” Controlled deployment requires a content-addressed calibration profile with sample count, observed failures, confidence level and finite-sample upper error bound.

## Harvard DASlab — self-designing data and RAG systems

Source: https://daslab.seas.harvard.edu/classes/cs265/

Adopted consequence: storage, indexing, retrieval and workload should be co-designed. KORPUS separates database candidate generation from bounded reranking and exposes a candidate budget instead of scanning all accessible spans.

## Harvard adversarial-attack dataset lineage

Source: https://dash.harvard.edu/handle/1/42719210

Adopted consequence: adversarial robustness requires large, evolving attack distributions. The included injection fixtures are mechanism checks only; a real red-team corpus remains an open production obligation.

## Rejected cargo cults

- Copying a frontier laboratory's model stack without its data, compute, threat model and evaluation evidence.
- Treating a leaderboard rank as system assurance.
- Adding agents where a deterministic transaction or state machine is sufficient.
- Replacing corpus governance with a larger context window.
- Calling an uncalibrated similarity score “confidence.”

## PostgreSQL — row security below the application

Sources:

- https://www.postgresql.org/docs/current/ddl-rowsecurity.html
- https://www.postgresql.org/docs/current/sql-altertable.html

Adopted consequence:

- application ABAC is not the final barrier;
- protected evidence tables use enabled and forced row-level security;
- tests execute through a non-superuser application role without `BYPASSRLS`;
- request-derived identity attributes are transaction-scoped database settings.

KORPUS implementation: migration `0002_database_defense_and_vectors`, server-applied identity settings, read/write policies and PostgreSQL integration assertions.

## OpenID Connect Core — identity is a verified protocol result

Source: https://openid.net/specs/openid-connect-core-1_0.html

Adopted consequence:

- issuer, audience, signature, expiry, algorithm and key identifier are independently checked;
- key rotation is handled through a bounded JWKS cache;
- missing `kid`, unapproved algorithms or unavailable required identity infrastructure fail closed;
- request bodies never assign roles, clearance or corpora.

KORPUS implementation: cached OIDC verifier with asymmetric-algorithm pinning and no controlled-mode development fallback.

## OpenTelemetry — portable operational traces

Sources:

- https://opentelemetry.io/docs/specs/otel/
- https://opentelemetry.io/docs/specs/semconv/

Adopted consequence:

- instrumentation is vendor-neutral and adapter-level;
- spans describe bounded operations and outcomes, not document or query contents;
- telemetry failure cannot alter authorization or answer semantics;
- semantic conventions are applied where a stable convention exists.

KORPUS implementation: OpenTelemetry initialization and low-information operational spans around the trust path.

## Prometheus — bounded metric cardinality

Source: https://prometheus.io/docs/practices/instrumentation/

Adopted consequence:

- labels are finite operational dimensions;
- user IDs, query text, source text and corpus IDs are prohibited labels;
- admission, latency, status and dependency outcomes are observable without creating an unbounded identity side channel.

KORPUS implementation: fixed-label counters, histograms and gauges with tests that reject sensitive/high-cardinality labels.

## Amazon S3 — end-to-end object integrity and retention

Sources:

- https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
- https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html

Adopted consequence:

- object keys are content-addressed;
- expected SHA-256 is checked before upload and persisted as metadata/checksum evidence;
- post-write verification compares returned metadata and content hash;
- governance retention is an explicit deployment option, not an assumed property.

KORPUS implementation: checksum-verified S3 adapter and immutable local equivalent.

## pgvector — rebuildable semantic candidates

Source: https://github.com/pgvector/pgvector

Adopted consequence:

- vectors are an index, not source authority;
- stored vectors bind model ID, dimensions and exact span text hash;
- semantic candidates remain subject to RLS, temporal validity, approval and exact evidence retrieval;
- HNSW parameters and dimensions are validated and versioned.

KORPUS implementation: `span_embeddings`, model-scoped HNSW DDL and bounded lexical/semantic candidate fusion.

## Google SRE — SLOs and error budgets as release control

Sources:

- https://sre.google/sre-book/service-level-objectives/
- https://sre.google/workbook/error-budget-policy/

Adopted consequence:

- local benchmark numbers do not become an SLA;
- a release gate composes explicit quality, integrity and bounded-work predicates;
- failed error/assurance budgets block release rather than being averaged away by unrelated success metrics;
- operational baselines require a minimum observation count and explicit provenance.

KORPUS implementation: machine-readable operational policy, release gate, local-measurement tags and drift placeholders that remain invalid until real observations exist.
