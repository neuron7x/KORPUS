# Repository Analysis — Baseline 578f4ea9caa93ec6211dbe914bf11ae110a6eaed

## Reviewed repository evidence

The current architecture SSOT describes KORPUS as an evidence-bound controlled-corpus
application, not an autonomous authority. Its product path requires authenticated identity,
entitlement, corpus/security authorization, authorized retrieval before materialization,
temporally valid approved evidence, support/contradiction gates, extractive claims/citations
or abstention, and tamper-evident audit.

`AGENTS.md` establishes the canonical workspace, isolated agent worktrees, protected `main`,
separation between implementation and verification, no request-body authorization
attributes, no retrieved text as system/tool instruction, and critical-mutant blocking.

`apps/api/pyproject.toml` already contains Pydantic 2, `httpx`, OpenTelemetry,
Prometheus, FastAPI, SQLAlchemy and the existing test stack. The base gateway therefore does
not require a new runtime dependency.

`adaptive_contracts.py` demonstrates explicit deterministic finite-domain validation.
`answer_audit_envelope.py` demonstrates request/session/service/policy audit binding.
`policy_evidence.py` explicitly distinguishes a policy-decision identifier used for audit
correlation from a capability token or alternate authorization mechanism.

## Architectural consequence

The correct KORPUS fit is an application-layer gateway with thin adapters. It must call the
live canonical identity, policy, egress, evidence, audit, transaction, configuration,
telemetry and release mechanisms rather than duplicate them.

## Live seam discovery required before implementation

A coding worker must locate, at its exact live HEAD:

1. authenticated principal/identity construction;
2. corpus/security/action authorization;
3. outbound egress policy;
4. request audit context;
5. audit persistence/chain append;
6. evidence admission and binding;
7. transaction/unit-of-work boundaries;
8. configuration and secret loading;
9. bootstrap/dependency injection;
10. runtime telemetry/health;
11. release/source identity.

Do not invent source paths for any seam not found in live code.
