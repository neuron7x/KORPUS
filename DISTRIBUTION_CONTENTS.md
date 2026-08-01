# KORPUS v5.0.0 distribution contents

Integrated engineering-assurance baseline for a controlled evidence platform. The distribution contains the executable project, the complete frozen v4 audit, v5 closure classification for all 99 findings, governance artifacts, deployment references and source-bound assurance evidence.

## Executable components

- FastAPI trust kernel with server-derived identity and content-addressed entitlement projection;
- need-to-know compartments, application ABAC and PostgreSQL `FORCE ROW LEVEL SECURITY`;
- opaque browser BFF session with OIDC authorization-code flow, PKCE, state, nonce and CSRF controls;
- streamed quarantine ingestion, MIME/signature checks, ClamAV contract, isolated parser subprocess, bounded OCR and durable leased jobs;
- immutable documents, temporal versions, source authenticity, near-duplicate and extraction-quality governance;
- separate metadata/content/approval reviewer credentials with scope, expiry and revocation;
- content-addressed corpus policy controlling classification, rights, operations, retention, legal hold and external embedding egress;
- bounded lexical retrieval, optional calibration-bound semantic retrieval, deterministic ranking and explicit abstention;
- exact claim-to-span evidence with offsets, quote/source hashes and contradiction checks;
- hash-chained audit ledger, CAS head, durable anchor outbox and authenticated remote checkpoint contract;
- same-origin dependency-free PWA;
- Docker Compose development topology and Kubernetes/Kustomize production reference topology;
- GitLab CI contracts, migrations, backup/restore tools, observability, validation and clean-room packaging;
- complete v4 audit PDF/DOCX/Markdown/JSON/CSV and v5 machine-readable closure register.

## Current local assurance evidence

- 172 tests collected: 171 PASS, 1 live-PostgreSQL SKIP, 0 failures/errors;
- combined line coverage 87.00% and branch coverage 66.87%;
- adversarial evaluation 30/30 PASS with 0 citation, leakage and determinism failures;
- selected critical mutation gate 26/26 killed;
- Alembic empty-database migration/schema parity PASS;
- SQLite FTS5 bounded scale probe PASS on 5,000 synthetic spans;
- operational composition gate PASS with `production_authorized=false`;
- web validation/typecheck/build PASS;
- OpenAPI, repository, infrastructure, Kubernetes and 99-finding closure contracts PASS.

All values above are local engineering measurements. They are not production SLA, independent TEVV or authorization.

## Audit closure state

| State | Count | Meaning |
|---|---:|---|
| `CLOSED_LOCAL` | 20 | Frozen local acceptance predicate has executable evidence. |
| `MITIGATED_LOCAL` | 33 | Material local control exists; live/corpus/independent acceptance remains. |
| `EXTERNAL_DEBT` | 31 | Cannot be closed inside source code or this environment. |
| `OPEN_TECH_DEBT` | 15 | Engineering implementation remains open. |

## Deliberately not claimed

- no claim that all possible vulnerabilities are known or removed;
- no real 5,960-file corpus, rights/classification approval or domain-owner acceptance;
- no live production proof for PostgreSQL/pgvector, Kubernetes, OIDC, S3 Object Lock, KMS/HSM, remote anchor or telemetry backend;
- no independent pentest, AI red-team, parser/container assessment or real-corpus TEVV;
- no signed production provenance, immutable registry promotion or legal license clearance;
- no production SLO, load/soak/chaos, failover, PITR, measured RTO/RPO or formal authorization.
