# АКТ РОЗШИРЕНОГО ТЕХНІЧНОГО, НАУКОВОГО ТА ОПЕРАЦІЙНОГО АУДИТУ «КОРПУС» v4.0.0

Дата: 2026-08-01  \nОб’єкт: KORPUS_INFRA_HARDENED_v4.0.0  \nСтатус: **FAIL для production; PASS_WITH_CAVEATS для controlled research/pilot на відкритих даних.**

## Межа твердження
Неможливо довести «100% усіх можливих вразливостей» нетривіальної системи. Цей акт містить **100% виявлених проблем у зафіксованому static/local scope**, а також окремий перелік неперевірених production-зон.

## Розрахункова production-readiness: **29.2/100 — EXTRAPOLATED**

| Домен | Вага | Бал /10 | Пояснення |
|---|---:|---:|---|
| Architecture & maintainability | 10% | 6.5 | Core boundaries are thoughtful; god objects/config complexity remain. |
| Functional/local correctness | 8% | 7.5 | 124 PASS + mutation/adversarial evidence, but mostly local/synthetic. |
| Scientific evaluation & calibration | 10% | 3.0 | 30 synthetic cases; no real blinded corpus or human gold set. |
| Identity & authorization | 10% | 3.0 | OIDC verifier exists; UI and entitlement/PDP/high-assurance controls absent. |
| Corpus/data governance | 10% | 1.0 | Real corpus, rights, classification and signed release absent. |
| Application/AI security | 10% | 3.0 | Some leakage/injection gates; no sandbox, fuzzing, independent red-team. |
| Infrastructure/deployment | 10% | 2.5 | Strong local design; no live production topology evidence. |
| SRE/DR/observability | 8% | 2.0 | Runbooks/design exist; no SLO, HA, live restore, on-call or durable telemetry. |
| Supply-chain assurance | 8% | 2.5 | SBOM/scans jobs exist; mutable tags, no hash lock/provenance/signing. |
| Privacy/legal/data lifecycle | 6% | 1.0 | Rights, retention, deletion, PII and legal-hold controls unproven. |
| Independent verification | 5% | 0.0 | No external assessment. |
| Operational authorization | 5% | 0.0 | Explicitly false. |

## Реєстр: 99 findings — P0=30, P1=56, P2=13

### P0

#### GOV-001 · Немає формальної production authorization
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Operational gate explicitly records production_authorized=false; немає risk owner, SSP/ATO або підписаного рішення про прийняття ризику.
- Наслідок: Запуск без юридично та організаційно визначеного власника ризику.
- Задача: Призначити system owner, data owner, security owner; створити authorization package і signed go/no-go.
- Інструменти/метод: NIST AI RMF; NIST RMF/SSP; threat-model workshop
- PASS: Підписаний authorization decision, scope, residual-risk register і expiry date.

#### GOV-002 · Немає use-case-specific AI risk profile
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Є загальні assurance-документи, але немає операційного профілю Govern→Map→Measure→Manage для конкретного військового застосування.
- Наслідок: Ризики оцінюються без визначеного контексту, шкоди, користувачів і допустимої помилки.
- Задача: Створити AI system card, context map, harm model, risk appetite, human-oversight policy.
- Інструменти/метод: NIST AI RMF / AIRC playbook
- PASS: Кожен risk має owner, metric, control, evidence і review cadence.

#### GOV-003 · Немає затвердженої класифікації та правил обробки даних
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Реальний корпус 5 960 файлів у release відсутній; classification guide, marking rules і handling matrix не надані.
- Наслідок: Можливий незаконний або небезпечний витік обмеженої інформації.
- Задача: Провести inventory, rights/classification review, labeling, compartment mapping, retention/declassification rules.
- Інструменти/метод: Data inventory; DLP; classification workshop; legal review
- PASS: 100% corpus objects мають owner, class, rights, retention, releasability і access policy.

#### GOV-004 · Немає незалежного TEVV, pentest і red-team
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Усі наявні докази створені самим репозиторієм; зовнішнього аудитора й blind tests немає.
- Наслідок: Self-confirming assurance: одна й та сама модель помилок у коді й тестах.
- Задача: Незалежний code review, API/cloud pentest, AI/RAG red-team, corpus poisoning exercise.
- Інструменти/метод: OWASP ASVS/API Top 10; OWASP GenAI; MITRE ATLAS; NIST Dioptra
- PASS: Незалежний звіт без відкритих P0/P1 та з повторною перевіркою remediation.

#### GOV-005 · Немає офіційної моделі предметної відповідальності
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Review separation перевіряє лише різні subject strings; кваліфікації, повноваження, конфлікти інтересів і підпис рішення відсутні.
- Наслідок: Неавторитетний reviewer може легалізувати неправильний документ.
- Задача: Registry reviewers/approvers, credential verification, COI policy, dual control, signed decisions.
- Інструменти/метод: PKI/e-sign; reviewer registry; workflow engine
- PASS: Кожне approval криптографічно прив’язане до уповноваженої ролі та scope.

#### GOV-006 · Права на індексацію, OCR, цитування й передачу документів не доведені
- Стан: `CONDITIONAL_RISK`
- Доказ: Source hash доводить байти, але не license, copyright, distribution authority або право надсилати текст зовнішньому embedding provider.
- Наслідок: Юридичне блокування продукту та disclosure третім сторонам.
- Задача: Провести rights clearance; заборонити external egress для неочищених класів.
- Інструменти/метод: Legal/IP review; data-processing agreements
- PASS: Для кожного джерела зафіксовані дозволені операції та заборони.

#### IAM-001 · Небезпечний secure-by-default: dev auth дає restricted admin
- Стан: `VERIFIED_DEFECT`
- Доказ: Settings defaults: environment=local, auth_mode=dev, subject local-admin, усі привілейовані ролі, clearance=restricted.
- Наслідок: Помилка deployment-конфігурації запускає систему з повним самопризначеним доступом.
- Задача: Заборонити dev auth у packaged runtime; вимагати explicit DEV_MODE acknowledgment і loopback-only binding.
- Інструменти/метод: Pydantic discriminated settings; policy-as-code; negative startup tests
- PASS: Будь-який non-test start без OIDC/explicit local override завершується exit!=0.

#### IAM-002 · Production web-клієнт не реалізує OIDC
- Стан: `VERIFIED_DEFECT`
- Доказ: public/app.js викликає /v1/answers без Authorization; UI працює лише з dev auth або зовнішньою ручною інʼєкцією токена.
- Наслідок: Користувач не може безпечно автентифікуватися в production.
- Задача: Реалізувати Authorization Code + PKCE, secure token handling/BFF, logout, expiry/refresh/error states.
- Інструменти/метод: OIDC conformance suite; Playwright; BFF pattern
- PASS: End-to-end OIDC login/logout/expiry/revocation проходить у staging.

#### IAM-003 · Привілеї напряму довіряються довільним OIDC claims
- Стан: `VERIFIED_DEFECT`
- Доказ: _identity_from_claims напряму приймає roles, clearance, corpora з токена без server-side entitlement map.
- Наслідок: Помилка IdP/client mapping може видати admin/restricted доступ.
- Задача: Ввести PDP/entitlement registry; allowlist claims; audience/client-specific mapping; deny unknown.
- Інструменти/метод: OPA/Cedar або власний PDP; contract tests
- PASS: Підроблені/невідомі claims не підвищують доступ; mapping version audited.

#### IAM-004 · Модель доступу не виражає need-to-know/compartments
- Стан: `CONDITIONAL_RISK`
- Доказ: AccessTier і Classification мають лише кілька рівнів; немає compartments, releasability, purpose, unit/mission, device posture.
- Наслідок: Користувач із формальним рівнем може бачити нерелевантний обмежений корпус.
- Задача: Розширити ABAC: compartments/caveats, purpose-of-use, affiliation, device trust, temporal/location policy.
- Інструменти/метод: OPA/Cedar; policy decision logs; model checking
- PASS: Набір cross-compartment noninterference tests PASS на DB і API.

#### ING-001 · Upload повністю буферизується в RAM
- Стан: `VERIFIED_DEFECT`
- Доказ: _read_upload_limited збирає list[bytes] і b"".join до 50 MB; concurrent ingestions множать memory pressure.
- Наслідок: Memory exhaustion/DoS і подвійне копіювання payload.
- Задача: Stream у quarantine object/file із incremental hash і hard quota; не зберігати повний bytes у RAM.
- Інструменти/метод: Streaming multipart; tempfile/object store; load tests
- PASS: Peak RSS bounded під N concurrent max-size uploads.

#### ING-002 · OCR/парсинг синхронні в API request
- Стан: `VERIFIED_DEFECT`
- Доказ: Ingestion виконує PdfReader, pdftoppm і tesseract у threadpool до відповіді; немає durable job state.
- Наслідок: Timeout, втрата роботи при restart, starvation API workers.
- Задача: Durable queue/workflow, idempotency key, resumable states, cancellation, retry/dead-letter.
- Інструменти/метод: Temporal/Celery/Arq; Postgres job ledger
- PASS: Crash/restart test завершує або безпечно повторює job без дублювання.

#### ING-003 · Немає malware scan/CDR до parser execution
- Стан: `VERIFIED_DEFECT`
- Доказ: У pipeline немає AV, YARA, CDR або quarantine decision перед pypdf/poppler/tesseract.
- Наслідок: Шкідливий документ атакує parser/toolchain.
- Задача: Quarantine service: magic sniffing, AV/YARA, CDR, parser sandbox; лише clean artifact далі.
- Інструменти/метод: ClamAV/YARA; CDR; sandboxed worker
- PASS: EICAR/malformed/polyglot fixtures блокуються до extraction.

#### ING-004 · Untrusted PDF парситься в API trust domain
- Стан: `VERIFIED_DEFECT`
- Доказ: pypdf працює in-process; poppler/tesseract запускаються у тому ж container namespace.
- Наслідок: Parser RCE/DoS отримує доступ до API secrets/DB/network.
- Задача: Винести extraction у disposable no-network sandbox з seccomp/AppArmor, read-only FS, uid, cgroup quotas.
- Інструменти/метод: gVisor/Firecracker/Kubernetes sandbox; seccomp
- PASS: Compromise simulation не бачить DB/IdP/S3 credentials і не має egress.

#### ING-005 · Aggregate OCR budget фактично не обмежений
- Стан: `VERIFIED_DEFECT`
- Доказ: 300 s timeout застосовується pdftoppm і окремо кожному tesseract page; до 500 pages.
- Наслідок: Один документ може зайняти години CPU та блокувати ingestion slots.
- Задача: Global wall-clock/CPU/pixel budget; per-page deadline; max rendered pixels; early abort.
- Інструменти/метод: cgroups; process supervisor; timeout budget tests
- PASS: Worst-case file завершується в заданий budget і очищає temp artifacts.

#### RAG-001 · Evaluation dataset є synthetic fixture, не production evidence
- Стан: `VERIFIED_DEFECT`
- Доказ: EVAL_REPORT: 30/30, calibration_status=UNVALIDATED_TEST_FIXTURE.
- Наслідок: Високий pass rate не прогнозує реальну точність на українському корпусі.
- Задача: Створити frozen stratified gold set із реальних документів і adversarial holdout.
- Інструменти/метод: Annotation platform; HELM-style scenario matrix; RAGChecker/ALCE metrics
- PASS: Blind holdout, human adjudication, versioned dataset, confidence intervals.

#### RAG-002 · Calibration profile не криптографічно звʼязаний з фактичним dataset artifact
- Стан: `VERIFIED_DEFECT`
- Доказ: Profile містить dataset_sha256, але Settings.load не звіряє hash з конкретним dataset file і не перевіряє signature/approver.
- Наслідок: Можна подати profile із вигаданими метриками/хешем.
- Задача: Signed calibration bundle: dataset, labels, code digest, metrics, profile, approvers.
- Інструменти/метод: in-toto/SLSA attestation; cosign; reproducible eval
- PASS: Runtime перевіряє signed bundle та точний dataset/code digest перед calibrated mode.

#### RAG-003 · Немає human gold standard та inter-annotator agreement
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: В release немає domain experts, adjudication protocol, Cohen/Fleiss kappa або disagreement set.
- Наслідок: Невідомо, чи ground truth взагалі стабільний і предметно правильний.
- Задача: Подвійна незалежна розмітка, adjudication, reviewer qualifications, ambiguity labels.
- Інструменти/метод: Label Studio/Argilla; statistical analysis
- PASS: IAA threshold predefined; ambiguous cases excluded/separately scored.

#### INF-001 · Docker/Compose runtime не був фактично виконаний у середовищі аудиту
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Release report explicitly marks container execution as external GitLab gate.
- Наслідок: Compose може не піднятися або інтеграції можуть бути невірно wired.
- Задача: Запустити clean host deployment, smoke/E2E, restart/upgrade/downgrade, network tests.
- Інструменти/метод: Docker/Podman; Testcontainers; GitLab runner
- PASS: Full stack starts from zero and passes E2E under non-root roles.

#### INF-002 · docker-compose.yml є local topology, не production deployment
- Стан: `VERIFIED_DEFECT`
- Доказ: environment=local, auth=dev, HTTP MinIO/OTLP, localhost port; single instances.
- Наслідок: Неприпустимо використовувати manifest як production.
- Задача: Створити окремі staging/prod IaC modules; видалити implicit promotion local compose.
- Інструменти/метод: Terraform/Pulumi; Helm/Kubernetes або hardened VMs
- PASS: Production config passes policy-as-code and has no dev settings/plain HTTP.

#### INF-003 · Немає production TLS ingress і service identity
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Nginx слухає HTTP 8080; внутрішні S3/OTLP HTTP у local compose; production ingress manifest відсутній.
- Наслідок: MITM/credential exposure при неправильній мережевій межі.
- Задача: TLS 1.2/1.3 ingress, mTLS/service mesh або equivalent, certificate rotation.
- Інструменти/метод: cert-manager/Envoy/Nginx; TLS scanners
- PASS: All external and sensitive internal paths cryptographically authenticated.

#### INF-004 · Немає HA/failover/PITR topology
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Один PostgreSQL, MinIO, API, web; немає replica/failover/WAL archive/multi-zone proof.
- Наслідок: Single point of failure та втрата даних.
- Задача: Define availability class; HA Postgres, object replication, redundant API, PITR.
- Інструменти/метод: Patroni/managed Postgres; object replication; chaos test
- PASS: Failover drill meets defined RTO/RPO with no authorization bypass.

#### INF-005 · Backup/restore не доведено на live production-like PostgreSQL
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Локально тестуються crypto/fake binaries; live job існує в CI, але не виконаний у цьому аудиті.
- Наслідок: Backup може бути невідновним у реальному середовищі.
- Задача: Quarterly live restore to isolated environment, data validation, RLS/auth tests, timed RTO/RPO.
- Інструменти/метод: pg_dump/pg_restore or physical backup; restore automation
- PASS: Independent restore evidence with measured RTO/RPO and checksum reconciliation.

#### INF-006 · Немає production secret manager/KMS/HSM і rotation evidence
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Local secrets — files; audit/backup keys in app runtime; rotation protocol не доведений.
- Наслідок: Компрометація host/app відкриває keys і audit forgery/decryption.
- Задача: Vault/KMS/HSM, workload identity, envelope encryption, rotation/revocation drills.
- Інструменти/метод: HashiCorp Vault/cloud KMS/HSM
- PASS: No long-lived static secrets in images/files; rotation without downtime tested.

#### SRE-001 · Немає SLO/SLI/error-budget contract
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Немає визначених availability, latency, freshness, ingestion durability, answer quality SLO.
- Наслідок: Неможливо обʼєктивно вирішити launch або regression.
- Задача: Define user journeys, SLIs, SLOs, error budget, alert policy.
- Інструменти/метод: Google SRE methods; Prometheus/OpenTelemetry
- PASS: Approved SLO document and burn-rate alerts validated.

#### SRE-002 · Немає on-call ownership та incident exercises
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Runbooks є, але немає roster, escalation, paging, game-day evidence, postmortems.
- Наслідок: Інцидент не буде вчасно виявлений/локалізований.
- Задача: On-call model, severity matrix, paging, tabletop + technical game days.
- Інструменти/метод: PagerDuty/Opsgenie equivalent; incident tooling
- PASS: Timed exercises meet detection/containment/recovery targets.

#### SUP-001 · Container/CI images pinned tags, not immutable digests
- Стан: `VERIFIED_DEFECT`
- Доказ: CI/Compose/Dockerfile use version tags (python, pgvector, Trivy, Syft, MinIO, BuildKit).
- Наслідок: Tag re-publish changes build без source change.
- Задача: Resolve and pin digest; automated verified update PRs; policy enforcement.
- Інструменти/метод: Renovate/Dependabot; cosign; registry policy
- PASS: All release inputs are digest-pinned and provenance records exact digests.

#### SUP-002 · Python lock files не містять hashes
- Стан: `VERIFIED_DEFECT`
- Доказ: pip install використовує versions і --no-deps, але не --require-hashes.
- Наслідок: Compromised index/artifact може підмінити wheel/sdist.
- Задача: Hash-pin all artifacts; private mirror; binary-only policy; provenance verification.
- Інструменти/метод: pip-tools/uv lock; --require-hashes; artifact registry
- PASS: Offline/reproducible install succeeds only for approved hashes.

#### SUP-003 · Немає signed build provenance і artifact signing
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Є SHA-256/manifest, але нема hosted-builder attestation, cosign signature, transparency log.
- Наслідок: Неможливо довести, хто/як побудував production image.
- Задача: Generate SLSA provenance, sign images/SBOM, verify before deploy.
- Інструменти/метод: GitLab OIDC + cosign/in-toto; SLSA verifier
- PASS: Deployment admission rejects unsigned/unexpected provenance.

#### DATA-001 · Немає enforceable retention/deletion/legal-hold policy
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Object lock retention є config, але corpus-specific lifecycle, deletion, legal hold, declassification не реалізовані end-to-end.
- Наслідок: Незаконне довічне зберігання або передчасне видалення доказів.
- Задача: Lifecycle state machine per data class; legal hold; cryptographic erasure; audit.
- Інструменти/метод: S3 lifecycle/KMS; policy engine
- PASS: Automated tests prove retain/delete/hold/declassify behavior.

### P1

#### IAM-005 · OIDC assurance неповний
- Стан: `VERIFIED_DEFECT`
- Доказ: Verifier не вимагає acr/amr, azp, typ, jti; OIDC path не вимагає nbf; немає revocation/replay cache.
- Наслідок: Використання слабкої автентифікації, replay або токена не того client context.
- Задача: Вимагати phishing-resistant MFA assurance, typ/azp, jti replay policy, revocation/CAE за можливості.
- Інструменти/метод: OIDC conformance; token replay tests
- PASS: Негативні тести для stale/replayed/wrong-client/low-assurance tokens PASS.

#### IAM-006 · RLS залежить від session GUC, який встановлює застосунок
- Стан: `VERIFIED_DEFECT`
- Доказ: PostgreSQL policy context задається set_config з identity від API. Компрометований app role/process може спробувати встановити ширший context.
- Наслідок: RLS захищає від помилки query, але не від app compromise/SQL execution.
- Задача: Винести authorization у signed session context або окремі DB roles; заборонити прямий SQL; перевірити role privileges.
- Інструменти/метод: PostgreSQL RLS tests; pgaudit; signed context
- PASS: App role не може самостійно розширити effective claims навіть через довільний SQL.

#### IAM-007 · Немає lifecycle entitlement/offboarding
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Не надано SCIM/HR source, deprovisioning SLA, periodic access review або stale-account tests.
- Наслідок: Звільнений/переведений користувач зберігає доступ.
- Задача: SCIM/IdP lifecycle, quarterly recertification, emergency revoke.
- Інструменти/метод: SCIM, IdP logs, access review
- PASS: Disable/revoke propagation виміряна та відповідає SLA.

#### IAM-008 · Немає PAM/break-glass control
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Admin роль існує, але немає just-in-time elevation, approval, session recording, emergency credentials.
- Наслідок: Постійний надмірний привілей і невідтворювані адміністративні дії.
- Задача: JIT/PAM, two-person approval, break-glass runbook, immutable session logs.
- Інструменти/метод: PAM/Vault; SIEM
- PASS: Усі privileged sessions attributable, time-bounded і reviewed.

#### ING-006 · File-type validation обмежена extension/MIME/PDF magic
- Стан: `VERIFIED_DEFECT`
- Доказ: Для txt/json/html немає libmagic/content sniffing; PDF перевіряє лише %PDF-.
- Наслідок: Polyglot/mislabeled content проходить до parser.
- Задача: libmagic + parser-specific structural validation; reject ambiguity.
- Інструменти/метод: python-magic/libmagic; corpus of polyglots
- PASS: Mismatch/polyglot suite fail-closed.

#### ING-007 · Regex-based HTML stripping не є безпечним parser
- Стан: `VERIFIED_DEFECT`
- Доказ: _strip_html використовує regex і втрачає структуру/може некоректно обробляти malformed HTML.
- Наслідок: Прихований/злитий текст, помилкові цитати, resource abuse.
- Задача: Парсер HTML allowlist, DOM text extraction, limits на depth/nodes.
- Інструменти/метод: lxml/html5lib sandbox; fuzzing
- PASS: Malformed HTML corpus не змінює смислові межі непередбачувано.

#### ING-008 · Object store write не атомарний із metadata transaction
- Стан: `VERIFIED_DEFECT`
- Доказ: object_store.put виконується до create_*_bundle; rollback БД залишає orphan object.
- Наслідок: Накопичення неврахованих даних і retention/privacy drift.
- Задача: Staging key + transactional outbox/commit marker + orphan reconciler/GC.
- Інструменти/метод: Saga/outbox; inventory reconciliation
- PASS: Injected DB failure не лишає доступного orphan або GC видаляє його за SLA.

#### ING-009 · Немає OCR/layout quality model
- Стан: `VERIFIED_DEFECT`
- Доказ: Зберігається текст і page, але немає confidence, bounding boxes, table/list structure, reading order quality.
- Наслідок: Цитата може бути формально привʼязана до хибного OCR.
- Задача: Layout-aware extraction, OCR confidence, low-confidence quarantine, visual review UI.
- Інструменти/метод: Document AI/layoutparser; OCR benchmarks
- PASS: CER/WER/table extraction виміряні по stratified corpus; low confidence не auto-approve.

#### ING-010 · Автентичність джерела не перевіряється
- Стан: `VERIFIED_DEFECT`
- Доказ: source_uri/issuer — metadata; немає digital signature, official registry reconciliation, TLS capture або trusted timestamp.
- Наслідок: Hash доводить лише отримані байти, не офіційність документа.
- Задача: Source connectors з domain allowlist, signature verification, publication ID reconciliation.
- Інструменти/метод: PKI/PAdES; registry API; timestamp service
- PASS: Authority status виникає лише після криптографічної/реєстрової перевірки або human attestation.

#### ING-011 · Deduplication лише exact SHA-256
- Стан: `VERIFIED_DEFECT`
- Доказ: OCR/reformat/scan copies одного документа мають різні hashes.
- Наслідок: Конфліктні дублікати, перекіс retrieval, зайва review-робота.
- Задача: Near-duplicate detection: simhash/minhash/layout/OCR fingerprint; canonical merge workflow.
- Інструменти/метод: datasketch; perceptual hash
- PASS: Known duplicate families обʼєднуються з precision/recall gate.

#### ING-012 · Немає corpus-scale ingestion recovery drill
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Немає доказу повторного імпорту тисяч файлів, resume, checkpoints, quarantine backlog і throughput.
- Наслідок: Масова міграція може зависнути або дати частковий корпус.
- Задача: Run full-scale replay with injected failures and deterministic reconciliation.
- Інструменти/метод: Workflow engine; fault injection; load generator
- PASS: 100% source manifest reconciled; no missing/duplicate versions.

#### RAG-004 · Evidence support вимірюється token overlap, не entailment
- Стан: `VERIFIED_DEFECT`
- Доказ: sentence_candidates/query_coverage та support score не доводять, що citation логічно підтримує claim.
- Наслідок: Правдоподібна, але не підтверджена відповідь проходить gate.
- Задача: Claim decomposition + NLI/attribution verifier + human spot checks; contradiction state.
- Інструменти/метод: NLI model/local verifier; ALCE; attribution benchmark
- PASS: Citation precision/completeness і entailment measured per claim, not query token overlap.

#### RAG-005 · Немає contradiction resolution між джерелами
- Стан: `VERIFIED_DEFECT`
- Доказ: Pipeline ранжує фрагменти, але не виявляє взаємно суперечливі чинні норми/редакції.
- Наслідок: Система обирає одну відповідь при невирішеному конфлікті.
- Задача: Conflict graph, issuer/jurisdiction precedence, explicit conflict abstention.
- Інструменти/метод: NLI contradiction; rule engine; temporal graph
- PASS: Known conflict cases повертають conflict status і всі релевантні sources.

#### RAG-006 · Citation completeness метрика не відповідає claim coverage
- Стан: `VERIFIED_DEFECT`
- Доказ: evidence_coverage формується з query token coverage; не рахує всі factual claims.
- Наслідок: Відповідь може мати citation, але частина тверджень лишається без доказу.
- Задача: Виділяти atomic claims і вимагати support для кожного; окремо correctness/completeness.
- Інструменти/метод: ALCE/RAGChecker-style metrics
- PASS: 100% emitted claims мають verified supporting spans або answer abstains.

#### RAG-007 · Authority priors є неперевіреними константами
- Стан: `VERIFIED_DEFECT`
- Доказ: OFFICIAL_UA=1.0, allied=.92, manufacturer=.78 тощо без empirical provenance.
- Наслідок: Скалярний prior може переважити релевантність і контекстну правову силу.
- Задача: Контекстна authority policy: document type, issuer competence, jurisdiction, date, task.
- Інструменти/метод: Policy rules + calibration/ablation
- PASS: Ablation і domain validation доводять користь; priors versioned and approved.

#### RAG-008 · Temporal score вимірює наявність metadata, не temporal relevance
- Стан: `VERIFIED_DEFECT`
- Доказ: _temporal_specificity=1.0 якщо effective_from існує, 0.6 для publication date.
- Наслідок: Старий документ отримує такий самий temporal bonus, як актуальний.
- Задача: Temporal distance/applicability features; interval algebra; supersession graph.
- Інструменти/метод: Bitemporal DB tests; temporal benchmark
- PASS: As-of queries правильно ранжують/відсікають historical/current versions.

#### RAG-009 · Risk classifier є regex heuristic
- Стан: `VERIFIED_DEFECT`
- Доказ: Query risk визначається невеликим набором pattern rules.
- Наслідок: Перефразування обходить stricter thresholds; false positives блокують корисні запити.
- Задача: Train/evaluate transparent risk classifier або rule DSL з broad test corpus; fail-closed unknown.
- Інструменти/метод: Property/adversarial tests; confusion matrix
- PASS: Per-class precision/recall + worst-group metrics на blind set.

#### RAG-010 · Prompt/control injection detector має лише пʼять regex patterns
- Стан: `VERIFIED_DEFECT`
- Доказ: contains_control_injection не покриває obfuscation, Unicode, multilingual, indirect instructions.
- Наслідок: Poisoned text може бути процитований/оброблений як evidence.
- Задача: Treat corpus as data structurally; instruction isolation; detector ensemble; poisoning metadata.
- Інструменти/метод: MITRE ATLAS cases; Unicode fuzzing; document taint labels
- PASS: Adversarial corpus suite із direct/indirect/obfuscated injection має defined outcomes.

#### RAG-011 · Sentence segmentation непридатна для складних нормативних документів
- Стан: `VERIFIED_DEFECT`
- Доказ: Regex [^.!?\n]+ не зберігає списки, таблиці, abbreviations, article/subclause hierarchy.
- Наслідок: Citation offsets і atomic claims можуть бути семантично неправильні.
- Задача: Structure-aware parser: headings, clauses, bullets, tables, references; immutable offsets.
- Інструменти/метод: PDF layout parser; Ukrainian sentence tokenizer
- PASS: Gold structural extraction benchmark PASS per document class.

#### RAG-012 · Lexical retrieval не має української морфології та domain analysis
- Стан: `VERIFIED_DEFECT`
- Доказ: Tokenizer лише casefold/regex/малий stoplist; немає lemmatization, synonyms, abbreviations.
- Наслідок: Recall падає через відмінки, військові скорочення, варіанти написання.
- Задача: Ukrainian analyzer, controlled vocabulary, acronym expansion, query rewriting with audit.
- Інструменти/метод: Stanza/UDPipe; domain thesaurus; BEIR-style evaluation
- PASS: Recall@20 та nDCG measured by query family, including morphology/acronyms.

#### RAG-013 · Немає тестів таблиць, чисел, одиниць і формул
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Eval fixtures переважно plain text; відсутні table-cell provenance і numeric consistency.
- Наслідок: Небезпечні помилки в дозах, строках, координатах, кількостях.
- Задача: Table extraction, unit normalization, numeric entailment, exact-cell citation.
- Інструменти/метод: Camelot/Docling/layout tools; unit tests
- PASS: Numeric/table benchmark має zero critical unit/sign errors.

#### RAG-014 · Scale evidence не репрезентує production
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: SCALE_REPORT: 5 000 synthetic spans, SQLite FTS5, 80 iterations, one target query, no concurrency/network.
- Наслідок: Невідомі p95/p99, saturation, recall і cost на реальному corpus/Postgres.
- Задача: Benchmark real corpus, concurrent mixed workload, cold/warm cache, failure cases.
- Інструменти/метод: k6/Locust; pg_stat_statements; OpenTelemetry
- PASS: SLO envelope with p50/p95/p99, throughput, recall, resource/cost curves.

#### RAG-015 · Embedding integration може створити data egress
- Стан: `CONDITIONAL_RISK`
- Доказ: HttpEmbeddingProvider надсилає query/span text зовнішньому endpoint; data-class policy не enforced у provider interface.
- Наслідок: Restricted content залишає trust boundary.
- Задача: Per-class provider policy, local models for restricted tiers, egress proxy/DLP, contracts/retention.
- Інструменти/метод: DLP; egress gateway; local embedding service
- PASS: Restricted test corpus ніколи не викликає external endpoint; network evidence confirms.

#### RAG-016 · Немає доказу synchronization/model migration embeddings
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Є upsert/search, але немає доведеного durable pipeline для backfill, stale vectors, dual-index migration й rollback.
- Наслідок: Semantic retrieval використовує неповний або змішаний index.
- Задача: Embedding job ledger, text_hash/model version reconciliation, blue-green index migration.
- Інструменти/метод: Queue; pgvector inventory; consistency checker
- PASS: 100% approved spans have correct model/text hash before semantic weight activation.

#### RAG-017 · Немає drift/online quality monitoring
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Відсутні production labels, distribution shift, query slice dashboards, alerting on abstention/recall proxies.
- Наслідок: Якість деградує непомітно після corpus/model/query changes.
- Задача: Shadow evaluation, sampled human review, drift metrics, rollback triggers.
- Інструменти/метод: Evidently/custom metrics; review queue
- PASS: Defined drift thresholds cause automatic freeze/rollback.

#### RAG-018 · Немає захисту від corpus/RAG poisoning як процесу
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Є окремі injection fixtures, але немає source anomaly detection, reputation/authority compromise scenario, poisoned update drill.
- Наслідок: Авторитетно оформлений шкідливий документ впливає на відповіді.
- Задача: Source provenance, anomaly detection, multi-review, canary corpus release, rollback.
- Інструменти/метод: MITRE ATLAS; content diff; signed releases
- PASS: Poisoned-source exercise detected before general release.

#### INF-007 · API має загальний egress без destination allowlist
- Стан: `VERIFIED_DEFECT`
- Доказ: Compose egress network дає API зовнішній вихід; немає proxy/policy by hostname/IP/data class.
- Наслідок: SSRF або compromised process exfiltrates corpus/secrets.
- Задача: Default-deny egress gateway; allowlist OIDC/S3/anchor/embedding; DNS/TLS pinning where appropriate.
- Інструменти/метод: NetworkPolicy/eBPF/proxy; SSRF tests
- PASS: Unexpected destinations unreachable; egress logs attributable.

#### INF-008 · Resource limits не калібровані capacity plan
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Compose CPU/memory/pids values є static; немає навантажувального provenance.
- Наслідок: OOM/throttling або зайве резервування.
- Задача: Load/capacity model by workload; autoscaling/admission budgets; saturation alerts.
- Інструменти/метод: k6/Locust; cAdvisor; pg metrics
- PASS: Limits derived from measured envelope and documented headroom.

#### INF-009 · OTel collector healthcheck перевіряє config, не serving path
- Стан: `VERIFIED_DEFECT`
- Доказ: Healthcheck запускає `otelcol validate`; не доводить, що receiver/exporter працює.
- Наслідок: Telemetry silently unavailable while container healthy.
- Задача: Use health_check extension endpoint + synthetic trace/metric canary.
- Інструменти/метод: OpenTelemetry Collector healthcheck; synthetic probe
- PASS: Dropped exporter/receiver causes readiness/alert according to policy.

#### INF-010 · Local audit anchor не є незалежним trust domain
- Стан: `VERIFIED_DEFECT`
- Доказ: Compose file anchor volume керується тим самим host/operator, що API/DB.
- Наслідок: Host compromise може змінити ledger і anchor.
- Задача: Remote append-only witness in separate account/org; asymmetric signatures/trusted timestamp.
- Інструменти/метод: Transparency log/Rekor-like service; HSM signing
- PASS: Single host/admin compromise cannot rewrite accepted history.

#### INF-011 · Немає deployment rollback/canary/schema compatibility proof
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: CI build/package є, але нема staged rollout, backward-compatible migrations, rollback under live traffic.
- Наслідок: Нова версія може зробити DB/clients незворотно несумісними.
- Задача: Expand-contract migrations, canary, automated rollback, compatibility tests.
- Інструменти/метод: Argo Rollouts/GitLab environments; contract tests
- PASS: N-1/N compatibility and rollback drill PASS.

#### INF-012 · Немає offsite/immutable backup schedule and retention execution
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Scripts/manifest є; scheduler, remote immutable target, retention/deletion monitoring не надані.
- Наслідок: Ransomware/operator error знищує primary і backup.
- Задача: 3-2-1 backups, object lock, isolated credentials, restore cadence.
- Інструменти/метод: Backup scheduler; WORM storage
- PASS: Backup age/immutability monitored; restore sampled automatically.

#### SRE-003 · Observability не має durable backend
- Стан: `VERIFIED_DEFECT`
- Доказ: OTel collector config у local topology фактично debug-oriented; нема metrics/logs/traces storage, dashboards, retention.
- Наслідок: Немає історичного аналізу, alerting і forensic evidence.
- Задача: Deploy metrics/traces/logs backend, RED/USE dashboards, retention and access controls.
- Інструменти/метод: Prometheus/Grafana/Loki/Tempo або managed stack
- PASS: Synthetic failures visible end-to-end and page correct owner.

#### SRE-004 · Немає chaos/failure-injection matrix
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Не доведені outages DB/S3/IdP/anchor/embedding/network/clock/disk-full.
- Наслідок: Невідомі cascading failures і ambiguous transaction outcomes.
- Задача: Fault injection per dependency, partial failures, latency, stale cache, clock skew.
- Інструменти/метод: Toxiproxy/Chaos Mesh; pytest integration
- PASS: Every dependency has defined degraded/fail-closed behavior and recovery evidence.

#### SRE-005 · Немає production load/concurrency endurance test
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Local scale probe single query/SQLite; немає soak, ingestion+query mixed load, connection-pool saturation.
- Наслідок: Race, leaks, queue collapse, p99 spikes зʼявляться лише в експлуатації.
- Задача: Mixed workload load/soak/spike tests; saturation and backpressure validation.
- Інструменти/метод: k6/Locust; pgbench; profiling
- PASS: Meet SLO under target and overload sheds load without leakage/corruption.

#### SRE-006 · Readiness має невизначену degraded-mode policy
- Стан: `CONDITIONAL_RISK`
- Доказ: Critical dependency failure може зробити instance unready; немає формальної read-only/lexical-only policy by risk class.
- Наслідок: Зайва недоступність або небезпечний silent fallback.
- Задача: Define dependency matrix: required/optional per environment/query risk; expose degraded state.
- Інструменти/метод: State machine; chaos tests
- PASS: Each outage returns predeclared status; no silent semantic/policy downgrade.

#### SRE-007 · Немає data/corpus release rollback drill
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Supersession/cache release logic тестується локально, але немає mass release/canary/rollback operational procedure.
- Наслідок: Poisoned або хибний corpus release впливає на всіх.
- Задача: Immutable corpus releases, canary cohort, shadow eval, atomic rollback.
- Інструменти/метод: Release registry; feature flags
- PASS: Rollback restores prior answers/index within defined RTO.

#### SUP-004 · BuildKit запускається з no-process-sandbox
- Стан: `VERIFIED_DEFECT`
- Доказ: CI sets BUILDKITD_FLAGS=--oci-worker-no-process-sandbox.
- Наслідок: Build steps мають слабшу isolation boundary.
- Задача: Use hardened hosted builder/runner or isolated VM; remove flag where feasible.
- Інструменти/метод: GitLab isolated runner; rootless BuildKit with sandbox
- PASS: Malicious build step cannot inspect other jobs/host secrets.

#### SUP-005 · Security scanners не були виконані в локальному аудиті
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Ruff/mypy/pip-audit/Trivy/Gitleaks jobs визначені, але tool results не надані з real GitLab run.
- Наслідок: Current dependencies/config may contain known issues.
- Задача: Run pipeline in isolated runner; archive signed reports; fix all policy violations.
- Інструменти/метод: GitLab CI; Trivy; pip-audit; Gitleaks; Ruff; mypy
- PASS: Signed pipeline evidence, zero unaccepted high/critical findings.

#### SUP-006 · Static security analysis coverage incomplete
- Стан: `VERIFIED_DEFECT`
- Доказ: CI має Ruff/Trivy/Gitleaks/pip-audit, але нема Semgrep/Bandit/CodeQL-equivalent, DAST, parser fuzzing.
- Наслідок: Logic/security flaws не представлені dependency/config scans.
- Задача: SAST rules, API DAST, fuzzing, IaC policies, secret history scan.
- Інструменти/метод: Semgrep/Bandit; Schemathesis/ZAP; Atheris
- PASS: Security test matrix maps every threat class to executable gate.

#### SUP-007 · GitLab branch/tag controls не доведені repository files
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: CODEOWNERS/CI exist, але protected branch, approval count, signed tags, runner isolation are server settings.
- Наслідок: Unilateral bypass або malicious runner може publish release.
- Задача: Export GitLab settings evidence; 2-person review; protected tags; isolated runners.
- Інструменти/метод: GitLab API/audit events; SLSA Source track
- PASS: No single contributor can alter protected release without independent approval.

#### SUP-008 · Немає continuous re-scan/patch SLA та KEV policy
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Одноразовий build scan не доводить стан через день після release.
- Наслідок: Нові CVE залишаються непоміченими.
- Задача: Scheduled rescans, SBOM inventory, KEV SLA, emergency rebuild/revoke.
- Інструменти/метод: Dependency Track/Grype/Trivy; CISA KEV feed
- PASS: High/critical/KEV triage and remediation SLA measured.

#### COD-001 · SqlRepository є infrastructure god object
- Стан: `VERIFIED_DEFECT`
- Доказ: repository.py ≈1 289 LOC, близько 46 functions; змішує schema, CRUD, search, audit, readiness, RLS context.
- Наслідок: Зростає change coupling і шанс неповного security fix.
- Задача: Розділити repositories/UoW: documents, versions, search, audit, health; transactional boundaries explicit.
- Інструменти/метод: Architecture tests; dependency-cruiser equivalent
- PASS: Кожен модуль має одну responsibility; security invariants tested across UoW.

#### COD-002 · Security config validator має надмірну цикломатичну складність
- Стан: `VERIFIED_DEFECT`
- Доказ: validate_security_and_calibration ≈CC 56, багато взаємозалежних modes.
- Наслідок: Конфігураційні комбінації важко довести; typo/новий mode може fail-open.
- Задача: Typed environment profiles/discriminated unions; policy table; exhaustive config tests.
- Інструменти/метод: Pydantic models; property-based testing
- PASS: All valid/invalid profile combinations generated and checked.

#### COD-003 · Broad `except Exception` у critical paths
- Стан: `VERIFIED_DEFECT`
- Доказ: Є у readiness/retrieval/extraction/semantic/object-store/anchor/resilience/routes.
- Наслідок: Різні failure causes collapse; programming bugs маскуються як dependency failure.
- Задача: Narrow exceptions, typed failure taxonomy, preserve cause, alert unexpected errors.
- Інструменти/метод: Ruff BLE; error budget tests
- PASS: Unexpected exception propagates to crash/alert in test, not generic safe-looking state.

#### COD-004 · Branch coverage значно нижча за statement coverage
- Стан: `VERIFIED_DEFECT`
- Доказ: Measured: statements 86.72%, branches 64.78%, combined 82.34%.
- Наслідок: Happy-path statements маскують неперевірені decision branches.
- Задача: Per-module branch thresholds for security-critical code; MC/DC-inspired cases.
- Інструменти/метод: coverage.py branch; diff coverage
- PASS: Auth/policy/ingestion/audit branches ≥90% or justified exclusions.

#### COD-005 · Mutation score 100% стосується лише 14 hand-selected mutants
- Стан: `VERIFIED_DEFECT`
- Доказ: MUTATION_REPORT: 14/14; це не exhaustive mutation testing.
- Наслідок: Неперевірені предикати можуть бути слабкими попри 100%.
- Задача: Run broad mutation engine by module; track equivalent mutants; risk-based mutation budget.
- Інструменти/метод: mutmut/cosmic-ray/custom operators
- PASS: Mutation score reported over declared operator space, survivors triaged.

#### COD-006 · Немає parser/API fuzzing
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Немає Hypothesis/Atheris/libFuzzer corpus for PDF metadata, JSON, HTML, multipart, JWT, query syntax.
- Наслідок: Crash/DoS/input edge cases невідомі.
- Задача: Coverage-guided fuzzing, property tests, regression corpus.
- Інструменти/метод: Atheris/Hypothesis; Schemathesis; OSS-Fuzz style
- PASS: No crash/hang/leak in defined CPU-hour budget; all findings regression-tested.

#### WEB-001 · UI покриває лише запит-відповідь
- Стан: `VERIFIED_DEFECT`
- Доказ: Немає production auth, ingestion, quarantine, review, approval, audit, corpus/version administration.
- Наслідок: Операційні процеси виконуються API/manual, що підвищує помилки й обходи.
- Задача: Role-specific consoles with safe workflows, validation, reason codes, audit previews.
- Інструменти/метод: Typed web app; E2E role tests
- PASS: All critical workflows executable without raw DB/API manipulation.

#### AUD-001 · Audit HMAC key доступний application process
- Стан: `VERIFIED_DEFECT`
- Доказ: Той самий процес генерує events і MAC. При full app compromise attacker може forge future history.
- Наслідок: Tamper evidence не захищає від повного compromise trust domain.
- Задача: Asymmetric signing/HSM or external append-only log; split duties.
- Інструменти/метод: HSM/KMS; transparency log; trusted timestamp
- PASS: Application cannot mint valid historical witness alone.

#### AUD-002 · Remote anchor protocol custom HTTP/HMAC
- Стан: `VERIFIED_DEFECT`
- Доказ: Немає стандартного transparency proof, asymmetric identity, external timestamp, multi-witness.
- Наслідок: Anchor service/operator compromise зменшує гарантії.
- Задача: Use signed append-only log / independent witnesses; key rotation and inclusion proofs.
- Інструменти/метод: Sigstore/Rekor-like; RFC3161 timestamp
- PASS: Offline verifier detects fork/truncation with independently trusted keys.

#### AUD-003 · Key rotation/recovery ceremony не доведена
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Немає live procedure for audit/backup/OIDC/service key rollover, compromise, re-encryption.
- Наслідок: Rotation може зламати verification або лишити compromised key valid.
- Задача: Versioned key IDs, dual validation window, revocation, ceremony and drill.
- Інструменти/метод: KMS/HSM; runbooks
- PASS: Rotation and compromised-key drill preserve verifiability and availability.

#### AUD-004 · Немає SIEM export/correlation/retention
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Audit chain локальна; durable security analytics and alert rules not demonstrated.
- Наслідок: Атаки виявляються запізно; forensic context розпорошений.
- Задача: Structured signed audit export to SIEM; correlation with IdP/network/deploy logs.
- Інструменти/метод: SIEM; OTel logs; pgaudit
- PASS: Defined attack simulations trigger alerts with complete timeline.

#### DATA-002 · Немає field-level privacy/minimization assessment
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Документи можуть містити персональні/операційні дані; немає PII detection/redaction workflow.
- Наслідок: Sensitive data індексується/цитується понад потребу.
- Задача: PII/secret scanning, redaction versions, purpose limitation, disclosure review.
- Інструменти/метод: DLP/NER; redaction tooling
- PASS: Known sensitive fixtures never appear in unauthorized retrieval/output/logs.

#### DATA-003 · Немає immutable corpus release manifest підписаного data owner
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Code release має manifest, але corpus release authority/signature/process не доведені.
- Наслідок: Неможливо довести точний набір документів, що породив відповідь.
- Задача: Signed corpus manifest: object/version hashes, policies, calibration, approvals.
- Інструменти/метод: in-toto/cosign; corpus registry
- PASS: Every answer resolves to signed corpus release accepted by data owner.

#### DATA-004 · Немає continuous inventory/reconciliation object store↔DB↔index
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Orphans/stale vectors/missing objects можуть виникнути; formal reconciliation job не доведений.
- Наслідок: Silent incompleteness або data residue.
- Задача: Scheduled bidirectional reconciliation with repair/quarantine and alerts.
- Інструменти/метод: Inventory jobs; checksums; pg queries
- PASS: Zero unexplained divergence; injected drift detected within SLA.

### P2

#### RAG-019 · Score не є каліброваною ймовірністю, але UI подає його як метрику
- Стан: `VERIFIED_DEFECT`
- Доказ: Convex utility bounded [0,1] не має probabilistic interpretation.
- Наслідок: Користувач може сприймати 0.8 як 80% істини.
- Задача: Rename to ranking utility; show calibrated risk/coverage separately; uncertainty UX.
- Інструменти/метод: Calibration plots; UX research
- PASS: UI/docs clearly distinguish utility, evidence coverage, error bound.

#### RAG-020 · Малі мінімальні вибірки не гарантують domain coverage
- Стан: `VERIFIED_DEFECT`
- Доказ: minimum 100 ranking queries/200 accepted samples без stratification.
- Наслідок: Aggregate metric маскує провал рідкісних критичних сценаріїв.
- Задача: Stratified sample-size plan per domain/risk; bootstrap confidence intervals; preregistered gates.
- Інструменти/метод: Power analysis; bootstrap
- PASS: Each critical stratum meets minimum N and upper error bound.

#### SUP-009 · Немає license/compliance inventory
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: SBOM jobs є, але license policy/notice/forbidden licenses не зафіксовані.
- Наслідок: Юридичний ризик distribution/deployment.
- Задача: License scan, approved license policy, notices.
- Інструменти/метод: Syft/ScanCode/FOSSA equivalent
- PASS: Release має complete license report і zero forbidden components.

#### COD-007 · mypy і Ruff policies слабкі для critical system
- Стан: `VERIFIED_DEFECT`
- Доказ: mypy ignore_missing_imports=true; Ruff selects limited rules.
- Наслідок: Integration types/security smells проходять непомічено.
- Задача: Strict typing by module, stubs/protocols, broader Ruff/security rules.
- Інструменти/метод: mypy strict/pyright; Ruff S/C90/BLE/ASYNC
- PASS: Zero unexplained Any at trust boundaries; complexity budgets enforced.

#### COD-008 · Web lint/typecheck є лише asset-existence validator
- Стан: `VERIFIED_DEFECT`
- Доказ: package scripts lint/typecheck обидва запускають validate.mjs; JS type semantics не перевіряються.
- Наслідок: UI auth/security regressions не ловляться.
- Задача: TypeScript, ESLint, DOM/unit/E2E tests, CSP tests.
- Інструменти/метод: TypeScript/ESLint/Vitest/Playwright
- PASS: OIDC/error/accessibility flows covered; real typecheck compiles.

#### COD-009 · Критичні модулі мають низьке покриття
- Стан: `VERIFIED_DEFECT`
- Доказ: cli 0%, semantic ≈40.7%, extraction ≈68%, auth ≈72%, OIDC ≈77%.
- Наслідок: Саме integration/security/error paths найменше перевірені.
- Задача: Raise targeted branch/mutation/failure-mode coverage, not aggregate only.
- Інструменти/метод: coverage/mutation/fault injection
- PASS: Per-risk module gates pass and no aggregate masking.

#### COD-010 · Немає API compatibility/consumer contract suite
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: JSON schemas є частково, але немає OpenAPI diff, backward compatibility, generated-client tests.
- Наслідок: Release ламає UI/інтеграції непомітно.
- Задача: OpenAPI freeze/diff, consumer-driven contracts, version/deprecation policy.
- Інструменти/метод: oasdiff/Schemathesis/Pact
- PASS: Breaking change requires major version and migration evidence.

#### WEB-002 · Немає accessibility/usability evidence
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: ARIA мінімальний; немає WCAG audit, keyboard/screen-reader tests, field error semantics.
- Наслідок: Частина користувачів не може надійно експлуатувати систему.
- Задача: WCAG 2.2 AA audit, keyboard/screen-reader, cognitive load tests.
- Інструменти/метод: axe-core/Playwright; manual AT testing
- PASS: Zero critical a11y defects; operational tasks pass usability tests.

#### OPS-001 · Немає доказу reproducible container build
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: Source ZIP deterministic-ish, але container bit-for-bit rebuild або reproducibility variance не виміряні.
- Наслідок: Build environment може неявно змінювати artifact.
- Задача: Rebuild on independent runner; compare digest; record allowed nondeterminism.
- Інструменти/метод: reproducible-build tooling; diffoscope
- PASS: Two independent builds yield identical digest or explained signed variance.

#### OPS-002 · CI retry може приховувати flaky infrastructure behavior
- Стан: `VERIFIED_DEFECT`
- Доказ: default retry=1 for runner timeout/system failure; flakiness metrics absent.
- Наслідок: Нестабільність маскується повторним PASS.
- Задача: Record retry count, fail on test retry, flake dashboard/quarantine policy.
- Інструменти/метод: GitLab analytics; pytest-rerun only diagnostic
- PASS: Release has zero unexplained flaky tests over defined window.

#### OPS-003 · Немає release evidence retention policy
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: GitLab package artifacts expire in 30 days; long-term audit archive not demonstrated.
- Наслідок: Пізніше неможливо відтворити evidence release.
- Задача: Immutable long-term evidence registry with retention aligned to system lifetime.
- Інструменти/метод: Artifact registry/WORM
- PASS: Every production release evidence retrievable and verified years later.

#### OPS-004 · Немає environment drift detection
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: No evidence of desired-state vs live infrastructure reconciliation.
- Наслідок: Manual changes bypass reviewed configuration.
- Задача: GitOps/IaC drift detection, admission policy, periodic attestation.
- Інструменти/метод: Terraform plan/OPA/Kyverno/GitOps
- PASS: Unauthorized drift detected and reverted/blocked.

#### OPS-005 · Немає cost/capacity governance
- Стан: `UNVERIFIED_BLOCKER`
- Доказ: API/OCR/embedding/storage costs and quotas are not modeled/alerted.
- Наслідок: Resource abuse або неконтрольована вартість.
- Задача: Per-tenant quotas, cost attribution, budget alerts, rate policy.
- Інструменти/метод: FinOps metrics; quota service
- PASS: Cost per ingest/query measured; budget breach triggers safe throttling.

## Протоколи

### PR-01 · Scope, threat model and data classification
- Мета: Freeze deployment context, actors, assets, trust boundaries, attack surfaces and data classes.
- Метод: STRIDE + LINDDUN + MITRE ATLAS mapping; misuse/abuse cases; data-flow diagrams.
- Інструменти: Threat model tool, DFD, classification registry, architecture decision records.
- PASS: All P0 attack paths have owner/control/test; no UNKNOWN trust boundary.

### PR-02 · Identity, entitlement and database noninterference
- Мета: Prove identity authenticity, least privilege and cross-compartment isolation.
- Метод: OIDC conformance, token abuse tests, entitlement mapping, RLS adversarial SQL, timing tests.
- Інструменти: IdP staging, OPA/Cedar, PostgreSQL, Schemathesis/pytest, pgaudit.
- PASS: Wrong/replayed/low-assurance token denied; arbitrary SQL cannot widen claims; zero leakage.

### PR-03 · Untrusted document quarantine and extraction
- Мета: Make parser compromise non-catastrophic and ingestion resumable.
- Метод: Streaming quarantine, AV/CDR, sandbox, resource budgets, job state machine, fault injection.
- Інструменти: ClamAV/YARA, CDR, gVisor/Firecracker, queue/workflow engine, fuzzers.
- PASS: Malicious/malformed files never reach trusted runtime; crash resumes idempotently.

### PR-04 · Corpus authority, versioning and reviewer governance
- Мета: Prove document authenticity, currency, ownership and approval authority.
- Метод: Registry reconciliation, signature checks, bitemporal/supersession tests, dual review, signed release.
- Інструменти: PKI/PAdES, corpus registry, workflow, cosign/in-toto.
- PASS: Every retrieved span belongs to signed approved release valid as-of query date.

### PR-05 · Retrieval, attribution and abstention calibration
- Мета: Measure retrieval and claim support on realistic blinded corpus.
- Метод: Stratified gold set, train/dev/test split, nDCG/MRR/Recall, ALCE/RAGChecker metrics, conformal/selective risk, bootstrap CIs.
- Інструменти: Annotation platform, evaluation harness, NLI verifier, statistical notebooks.
- PASS: Pre-registered thresholds pass on untouched holdout and worst critical strata.

### PR-06 · AI/RAG adversarial security
- Мета: Attack injection, poisoning, leakage, evasion, denial of service and excessive trust.
- Метод: MITRE ATLAS/OWASP scenarios, poisoned corpus canary, Unicode/obfuscation fuzz, egress monitoring.
- Інструменти: Dioptra/custom harness, DLP, red-team tooling, fault injector.
- PASS: No unauthorized disclosure/action; detected poisoning rolls back before general release.

### PR-07 · Secure software supply chain
- Мета: Prove exact source→build→artifact lineage and dependency integrity.
- Метод: Digest pinning, hash locks, isolated builds, SBOM, SAST/SCA, signed provenance, two-party review.
- Інструменти: GitLab protected branches, cosign/in-toto, Syft/Trivy, Semgrep, pip-audit.
- PASS: Deploy gate verifies SLSA provenance/signature/SBOM; no unaccepted high/critical issue.

### PR-08 · Production topology, load and chaos
- Мета: Prove service survives expected load and dependency failures.
- Метод: Staging parity, mixed load/soak, saturation, chaos, canary, rollback, DB/object failover.
- Інструменти: k6/Locust, Toxiproxy/Chaos Mesh, OpenTelemetry, pg tools.
- PASS: SLOs met; overload sheds safely; failover/rollback preserve data and authorization.

### PR-09 · Backup, restore and cryptographic recovery
- Мета: Prove recovery, not merely backup creation.
- Метод: 3-2-1/WORM, timed restore, key rotation/revocation, PITR, integrity and access checks.
- Інструменти: KMS/HSM, backup platform, isolated restore environment.
- PASS: Measured RPO/RTO pass; restored system passes RLS, corpus and audit verification.

### PR-10 · Production Readiness Review and authorization
- Мета: Convert evidence into accountable launch decision.
- Метод: Independent PRR, runbooks/on-call, incident game day, residual-risk acceptance, staged launch.
- Інструменти: Google SRE PRR checklist, NIST AI RMF/SSDF dossier, sign-off workflow.
- PASS: All P0 closed; P1 explicitly accepted/mitigated; signed time-bounded authorization issued.