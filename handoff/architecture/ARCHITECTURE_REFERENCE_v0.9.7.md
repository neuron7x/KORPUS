# KORPUS v0.9.7 — Canonical Architecture Reference

## Architectural intent

KORPUS is a bounded-evidence, multi-tenant knowledge and inference system. It separates domain policy, application orchestration, HTTP/UI transport, persistence, security, evidence governance and deployment control. Retrieval or model output alone never authorizes a user-facing answer: tenancy, authorization, evidence authority, citation integrity, abstention and governance remain independent gates.

## Runtime decomposition

### API
- `apps/api/src/korpus/main.py` — composition root.
- `korpus/api/` — HTTP adapters: health, auth, client bootstrap, answers, corpus/ingestion, review, audit, inference, offline, billing, tenancy, admin.
- `korpus/application/` — use cases, retrieval/evidence, PEC/DGC, reliability, subscriptions, governance and release assurance.
- `korpus/domain/` — domain objects and invariants.
- `korpus/infrastructure/` — repositories, database/FTS, object storage, extraction and service adapters.
- `korpus/security/` — security boundary/scanning components.

### Web
- `apps/web/public/api.js` — network transport boundary.
- `transport_contract.js` — generated release/OpenAPI transport contract.
- `routes.js` / `workspace_routes.js` — navigation projection from server-effective permissions and runtime capabilities.
- consumer components — chat, conversations, readers, billing, offline pack.
- `console*.js` — operator/admin surfaces.
- `sw.js` — service-worker cache boundary.

`GET /v1/client/bootstrap` is the server-authoritative projection used by the UI. UI visibility is not a security boundary; backend policy remains authoritative.

## Public API contract

OpenAPI paths: **31**.

| Path | Methods |
|---|---|
| `/health` | GET |
| `/ready` | GET |
| `/v1/account` | GET |
| `/v1/admin/accounts` | GET |
| `/v1/admin/accounts/{account_id}/status` | POST |
| `/v1/admin/accounts/{auth_subject}` | GET |
| `/v1/answers` | POST |
| `/v1/audit/events` | GET |
| `/v1/audit/verify` | GET |
| `/v1/auth/me` | GET |
| `/v1/billing/checkout` | POST |
| `/v1/client/bootstrap` | GET |
| `/v1/conversations` | GET, POST |
| `/v1/conversations/{conversation_id}` | GET |
| `/v1/conversations/{conversation_id}/archive` | POST |
| `/v1/conversations/{conversation_id}/ask` | POST |
| `/v1/document-versions/{version_id}/rescission` | POST |
| `/v1/document-versions/{version_id}/review` | POST |
| `/v1/document-versions/{version_id}/spans` | GET |
| `/v1/documents` | GET |
| `/v1/documents/ingest` | POST |
| `/v1/documents/{document_id}/ingestion-jobs` | POST |
| `/v1/documents/{document_id}/versions/ingest` | POST |
| `/v1/inference/status` | GET |
| `/v1/ingestion-jobs/documents` | POST |
| `/v1/ingestion-jobs/{job_id}` | GET |
| `/v1/offline-pack` | POST |
| `/v1/offline-pack/key` | GET |
| `/v1/plans` | GET |
| `/v1/spans/{span_id}` | GET |
| `/v1/subscription` | GET, POST |

## Primary data flow

`Browser → OpenAPI-bound transport → authentication/tenancy → application policy → retrieval/evidence → answer/refusal → audit persistence → browser projection`

Ingestion:

`upload → malware/content validation → immutable document version → extraction/spans → indexing/embedding → review/publication → retrieval eligibility`.

## Evidence/admission flow

`behavioral source freeze → regression/mutation/eval/migration/scale → source-bound receipts → hard predicates → external evidence → final authorization`.

Current identity: release `v0.9.7`, source `15f1630f4327babeba37802d64b195d43cae256b55042b7f44517a24784a78aa`, collection `2345`, collection digest `ee46be90d262721d5545e772f7fefdd40df80e0dd4d0206c3072af992087082e`, module budget `456`, OpenAPI paths `31`.
