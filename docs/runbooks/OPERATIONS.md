# Operations runbook

## Service-level indicators

Availability, retrieval p95, time to first token, answer completion, abstention rate,
citation coverage, provider errors, queue age, index freshness and cost per successful
task. Alert on user-impacting symptoms, not raw CPU alone.

## Daily

Check failed ingestion, dead-letter queue, source revocations, access anomalies,
provider errors and backups.

## Weekly

Review corrections, unresolved corpus conflicts, eval drift, cost/latency by route,
dependency findings and capacity.

## Recovery

Target MVP RPO: 24 hours; RTO: 8 hours. These are hypotheses until a restore drill
demonstrates them. Quarterly restore into an isolated environment and verify database,
objects, permissions and index reconstruction.

