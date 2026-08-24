# Threat Model — v5

## Protected assets

Corpus bytes and metadata; identity/entitlement data; reviewer authority; source/reviewer signing keys; queries; answers/citations; embedding vectors; audit ledger/anchor; backups; build provenance; deployment credentials.

## Trust boundaries

1. browser ↔ reverse proxy/BFF;
2. BFF/API ↔ OIDC provider;
3. API/worker ↔ PostgreSQL application role;
4. quarantine ↔ scanner/parser worker;
5. API/worker ↔ object store;
6. API ↔ embedding service;
7. database outbox ↔ remote audit anchor;
8. GitLab runner ↔ registry/deployment environment;
9. reviewers/approvers ↔ governed workflow.

## Priority attack paths

| Path | Required control and evidence |
|---|---|
| forged privileged OIDC claims | server-side entitlement projection; negative token tests; IdP conformance |
| stolen browser session/CSRF | HttpOnly AES-GCM session, Secure host cookies, double-submit CSRF, TTL, logout/revocation tests |
| cross-corpus leakage | ABAC + compartments + PostgreSQL FORCE RLS + non-superuser integration tests |
| malicious upload/parser exploit | bounded streaming, MIME/signature checks, ClamAV, subprocess sandbox, page/time/output limits, fuzzing |
| source forgery | Ed25519 detached signature bound to bytes and normative metadata; key validity/revocation |
| reviewer self-authorization | separate subjects plus content-addressed scoped reviewer registry and recorded credential IDs |
| RAG poisoning/control injection | quarantine/review barriers, source instruction detector, exact extractive answer policy, contradiction gate |
| external embedding exfiltration | corpus-level operation policy checked before provider call, destination/token controls, DLP logs |
| audit rewrite/truncation | chain, HMAC, CAS head, durable outbox, independent monotonic anchor and restore verification |
| software supply-chain substitution | immutable image digests, signed provenance, SBOM, scanner gates and protected tags |
| resource exhaustion | bounded upload/parser/retrieval/output budgets, admission control, quotas and load evidence |

## Residual uncertainty

Unknown parser zero-days, insider misuse, compromised IdP/KMS/runner, covert channels, model-provider retention, and undiscovered attack classes cannot be eliminated by local tests. They require independent red-team, live telemetry, vendor controls, segmentation, rotation, and accountable residual-risk acceptance.
