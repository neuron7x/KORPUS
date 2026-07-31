# Distribution contents

This distribution is a GitLab-ready controlled-corpus engineering repository.

Included executable components:

- FastAPI API and OpenAPI contract;
- SQLite/PostgreSQL-compatible SQLAlchemy persistence;
- Alembic initial migration;
- content-addressed local object store;
- PDF embedded-text extraction and Tesseract OCR fallback;
- immutable canonical documents, versions and evidence spans;
- quarantine, metadata review, content review and approval workflow;
- JWT/fixed-local identity and pre-retrieval ABAC;
- lexical retrieval, supersession exclusion and temporal validity filtering;
- extractive claim-to-span answers with source hashes;
- HMAC-SHA256 hash-chained persistent audit;
- offline-capable dependency-free PWA;
- frozen evaluations and adversarial access fixtures;
- GitLab CI, CODEOWNERS, MR template, SBOM, secret/dependency scans;
- Dockerfiles, Compose support, runbooks and agent worktree protocol;
- deterministic repository manifest and source packaging scripts.

Not included because they require external authority or deployment-specific assets:

- the claimed 5,960-file real corpus;
- rights and classification decisions;
- appointed domain reviewers;
- production identity provider and signing keys;
- formal security profile, penetration-test report, authorization/accreditation;
- production cloud/on-premise infrastructure and monitoring ownership.
