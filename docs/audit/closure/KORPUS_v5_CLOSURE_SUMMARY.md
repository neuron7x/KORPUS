# KORPUS v5 audit closure summary

This register classifies all 99 v4 findings without converting missing external evidence into PASS.

| Status | Count | Meaning |
|---|---:|---|
| CLOSED_LOCAL | 24 | Executable local acceptance predicate passed. |
| MITIGATED_LOCAL | 55 | Material control exists; live, corpus, or independent acceptance remains. |
| EXTERNAL_DEBT | 20 | Cannot be closed inside this repository/session. |
| OPEN_TECH_DEBT | 0 | Engineering implementation remains open. |

## Remaining blockers

- **GOV-001 · P0 · EXTERNAL_DEBT** — Немає формальної production authorization
- **GOV-002 · P0 · MITIGATED_LOCAL** — Немає use-case-specific AI risk profile
- **GOV-003 · P0 · MITIGATED_LOCAL** — Немає затвердженої класифікації та правил обробки даних
- **GOV-004 · P0 · EXTERNAL_DEBT** — Немає незалежного TEVV, pentest і red-team
- **GOV-005 · P0 · MITIGATED_LOCAL** — Немає офіційної моделі предметної відповідальності
- **GOV-006 · P0 · EXTERNAL_DEBT** — Права на індексацію, OCR, цитування й передачу документів не доведені
- **IAM-002 · P0 · MITIGATED_LOCAL** — Production web-клієнт не реалізує OIDC
- **IAM-005 · P1 · MITIGATED_LOCAL** — OIDC assurance неповний
- **IAM-006 · P1 · MITIGATED_LOCAL** — RLS залежить від session GUC, який встановлює застосунок
- **IAM-007 · P1 · MITIGATED_LOCAL** — Немає lifecycle entitlement/offboarding
- **IAM-008 · P1 · EXTERNAL_DEBT** — Немає PAM/break-glass control
- **ING-008 · P1 · MITIGATED_LOCAL** — Object store write не атомарний із metadata transaction
- **ING-009 · P1 · MITIGATED_LOCAL** — Немає OCR/layout quality model
- **ING-012 · P1 · MITIGATED_LOCAL** — Немає corpus-scale ingestion recovery drill
- **RAG-001 · P0 · EXTERNAL_DEBT** — Evaluation dataset є synthetic fixture, не production evidence
- **RAG-003 · P0 · EXTERNAL_DEBT** — Немає human gold standard та inter-annotator agreement
- **RAG-005 · P1 · MITIGATED_LOCAL** — Немає contradiction resolution між джерелами
- **RAG-007 · P1 · MITIGATED_LOCAL** — Authority priors є неперевіреними константами
- **RAG-009 · P1 · MITIGATED_LOCAL** — Risk classifier є regex heuristic
- **RAG-010 · P1 · MITIGATED_LOCAL** — Prompt/control injection detector має лише пʼять regex patterns
- **RAG-011 · P1 · MITIGATED_LOCAL** — Sentence segmentation непридатна для складних нормативних документів
- **RAG-012 · P1 · MITIGATED_LOCAL** — Lexical retrieval не має української морфології та domain analysis
- **RAG-013 · P1 · MITIGATED_LOCAL** — Немає тестів таблиць, чисел, одиниць і формул
- **RAG-014 · P1 · MITIGATED_LOCAL** — Scale evidence не репрезентує production
- **RAG-015 · P1 · MITIGATED_LOCAL** — Embedding integration може створити data egress
- **RAG-016 · P1 · MITIGATED_LOCAL** — Немає доказу synchronization/model migration embeddings
- **RAG-017 · P1 · MITIGATED_LOCAL** — Немає drift/online quality monitoring
- **RAG-018 · P1 · MITIGATED_LOCAL** — Немає захисту від corpus/RAG poisoning як процесу
- **RAG-020 · P2 · MITIGATED_LOCAL** — Малі мінімальні вибірки не гарантують domain coverage
- **INF-001 · P0 · MITIGATED_LOCAL** — Docker/Compose runtime не був фактично виконаний у середовищі аудиту
- **INF-002 · P0 · MITIGATED_LOCAL** — docker-compose.yml є local topology, не production deployment
- **INF-003 · P0 · EXTERNAL_DEBT** — Немає production TLS ingress і service identity
- **INF-004 · P0 · EXTERNAL_DEBT** — Немає HA/failover/PITR topology
- **INF-005 · P0 · MITIGATED_LOCAL** — Backup/restore не доведено на live production-like PostgreSQL
- **INF-006 · P0 · EXTERNAL_DEBT** — Немає production secret manager/KMS/HSM і rotation evidence
- **INF-007 · P1 · MITIGATED_LOCAL** — API має загальний egress без destination allowlist
- **INF-008 · P1 · EXTERNAL_DEBT** — Resource limits не калібровані capacity plan
- **INF-009 · P1 · MITIGATED_LOCAL** — OTel collector healthcheck перевіряє config, не serving path
- **INF-010 · P1 · MITIGATED_LOCAL** — Local audit anchor не є незалежним trust domain
- **INF-011 · P1 · MITIGATED_LOCAL** — Немає deployment rollback/canary/schema compatibility proof
- **INF-012 · P1 · EXTERNAL_DEBT** — Немає offsite/immutable backup schedule and retention execution
- **SRE-001 · P0 · EXTERNAL_DEBT** — Немає SLO/SLI/error-budget contract
- **SRE-002 · P0 · EXTERNAL_DEBT** — Немає on-call ownership та incident exercises
- **SRE-003 · P1 · MITIGATED_LOCAL** — Observability не має durable backend
- **SRE-004 · P1 · MITIGATED_LOCAL** — Немає chaos/failure-injection matrix
- **SRE-005 · P1 · MITIGATED_LOCAL** — Немає production load/concurrency endurance test
- **SRE-006 · P1 · MITIGATED_LOCAL** — Readiness має невизначену degraded-mode policy
- **SRE-007 · P1 · MITIGATED_LOCAL** — Немає data/corpus release rollback drill
- **SUP-003 · P0 · EXTERNAL_DEBT** — Немає signed build provenance і artifact signing
- **SUP-005 · P1 · MITIGATED_LOCAL** — Security scanners не були виконані в локальному аудиті
- **SUP-006 · P1 · MITIGATED_LOCAL** — Static security analysis coverage incomplete
- **SUP-007 · P1 · EXTERNAL_DEBT** — GitLab branch/tag controls не доведені repository files
- **SUP-008 · P1 · EXTERNAL_DEBT** — Немає continuous re-scan/patch SLA та KEV policy
- **SUP-009 · P2 · MITIGATED_LOCAL** — Немає license/compliance inventory
- **COD-001 · P1 · MITIGATED_LOCAL** — SqlRepository є infrastructure god object
- **COD-004 · P1 · MITIGATED_LOCAL** — Branch coverage значно нижча за statement coverage
- **COD-005 · P1 · MITIGATED_LOCAL** — Mutation score 100% стосується лише 14 hand-selected mutants
- **COD-006 · P1 · MITIGATED_LOCAL** — Немає parser/API fuzzing
- **COD-007 · P2 · MITIGATED_LOCAL** — mypy і Ruff policies слабкі для critical system
- **COD-008 · P2 · MITIGATED_LOCAL** — Web lint/typecheck є лише asset-existence validator
- **COD-009 · P2 · MITIGATED_LOCAL** — Критичні модулі мають низьке покриття
- **WEB-001 · P1 · MITIGATED_LOCAL** — UI покриває лише запит-відповідь
- **WEB-002 · P2 · EXTERNAL_DEBT** — Немає accessibility/usability evidence
- **AUD-001 · P1 · MITIGATED_LOCAL** — Audit HMAC key доступний application process
- **AUD-002 · P1 · MITIGATED_LOCAL** — Remote anchor protocol custom HTTP/HMAC
- **AUD-003 · P1 · EXTERNAL_DEBT** — Key rotation/recovery ceremony не доведена
- **AUD-004 · P1 · MITIGATED_LOCAL** — Немає SIEM export/correlation/retention
- **DATA-001 · P0 · MITIGATED_LOCAL** — Немає enforceable retention/deletion/legal-hold policy
- **DATA-002 · P1 · MITIGATED_LOCAL** — Немає field-level privacy/minimization assessment
- **DATA-003 · P1 · MITIGATED_LOCAL** — Немає immutable corpus release manifest підписаного data owner
- **DATA-004 · P1 · MITIGATED_LOCAL** — Немає continuous inventory/reconciliation object store↔DB↔index
- **OPS-001 · P2 · MITIGATED_LOCAL** — Немає доказу reproducible container build
- **OPS-003 · P2 · EXTERNAL_DEBT** — Немає release evidence retention policy
- **OPS-004 · P2 · MITIGATED_LOCAL** — Немає environment drift detection
- **OPS-005 · P2 · EXTERNAL_DEBT** — Немає cost/capacity governance
