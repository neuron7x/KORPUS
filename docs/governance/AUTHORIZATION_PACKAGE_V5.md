# Production Authorization Package — required evidence

No repository commit can self-authorize production. The accountable authorization package must contain immutable references to:

1. named system, data, security, reliability, and mission owners;
2. intended use, prohibited use, users, data classes, harms, and risk appetite;
3. signed corpus inventory and rights/classification decisions;
4. threat model and control traceability matrix;
5. independent TEVV, API/cloud pentest, AI/RAG red-team, and remediation retest;
6. production architecture, service identities, TLS, secrets/KMS/HSM, egress, HA and PITR;
7. measured SLO/SLI, capacity, load, soak, chaos, RTO and RPO results;
8. signed build provenance, SBOM, vulnerability results, license inventory, and image digests;
9. reviewer/approver authority and conflict-of-interest process;
10. incident response, on-call, rollback, key rotation, backup restore, and declassification exercises;
11. residual-risk register with owner, expiry, compensating controls, and signed go/no-go.

Acceptance predicate: every P0/P1 finding is closed by independently reproducible evidence or explicitly accepted by the accountable risk owner with expiry. “Tests passed” is insufficient.
