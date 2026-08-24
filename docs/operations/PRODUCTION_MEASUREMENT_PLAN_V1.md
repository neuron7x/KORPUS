# Production measurement plan v1

## Objective

Convert the current explicit `UNKNOWN` production SLO state into evidence-based targets without inventing numbers.

## Measurement phases

### Phase A — controlled pilot

Collect a minimum of 1,000 representative authenticated requests across the intended endpoint mix, plus ingestion/review events. Segment by endpoint class, corpus size class, authorization scope, cache state and provider path. Report distribution summaries, not only means.

### Phase B — concurrency ladder

Increase concurrency in predetermined steps until one of these first occurs: admission refusal, latency knee, database pool saturation, lock contention, provider rate limit or error-budget breach once an error budget is approved. The knee is a capacity observation, not automatically the production limit.

### Phase C — soak

Run long enough to expose queue accumulation, connection leaks, storage growth, audit reconciliation lag and retry amplification. Preserve p50/p95/p99 plus maxima and time series.

### Phase D — failure injection

Inject dependency timeout, database restart, provider refusal, object-store failure, audit-anchor unavailability and worker crash. Measure recovery semantics and whether failures remain fail-closed.

## Statistical rules

- Never report p95 from fewer than 100 observations in the measured class.
- Report sample count with every percentile.
- Keep cold-start and steady-state distributions separate.
- Treat censored/refused requests explicitly; do not remove them from denominator silently.
- Do not aggregate authorization denials with server errors.
- Report confidence/uncertainty for calibrated rates where the policy requires it.
- Preserve raw event IDs or deterministic hashes so summaries can be recomputed.

## Promotion rule

A production numeric target can be adopted only when the measured workload is declared representative, the consequence class is documented, and the target is approved as policy. Until then, local engineering thresholds (for example the existing 50 ms local scale probe) remain engineering gates only.
