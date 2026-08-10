# KORPUS v6.7.0 — Security / Reliability / Assurance Audit

Generated: 2026-08-09T21:29:19.615744+00:00
Source manifest: `362e0a28eb34f0ef8f83091a7f488f726e388cba0ffb153853793c56ea9b4a6f` / 604 files / PASS

## 1. INTENT

Audit and harden the uploaded canonical repository against reachable security failures, dependency drift, inference-boundary failures, reliability faults, and false assurance. The production release gate is fail-closed: missing evidence is a failure, not an inferred pass.

## 2. VERIFIED STATE

- Full test execution: **1303 tests; 1 failure; 0 errors; 3 skipped**. Procedure: 149 test files executed in six sequential shards and JUnit testcases aggregated. Result decomposition: **1299 passed, 1 failed, 3 skipped**. The only failure is the intentionally stale promoted-assurance digest after source remediation. **ANCHORED_LOCAL**.
- Coverage: line **0.9162** vs policy **0.82**; branch **0.7891** vs policy **0.75**. Sharded collection + `coverage combine` + policy script. **ANCHORED_LOCAL**.
- Mutation catalogue: **246** unique full mutant IDs; structural target/test gates PASS. Changed-risk probe: **23/23 killed**, score **1.0**. Full 246-mutant fresh execution did not finish inside the execution ceiling; aggregate mutation status is **UNKNOWN**, not PASS.
- Eval fixture: **30/30** pass; citation failures **0**; leakage failures **0**; determinism failures **0**. The repository itself marks this dataset `UNVALIDATED_TEST_FIXTURE` and `tevv.admissible_as_tevv=false`; therefore this is not TEVV closure.
- Chaos matrix: **8/8 local scenarios** reached expected fail-closed semantics; database removal became HTTP 503 and hostile planner text did not leak. **ANCHORED_LOCAL**.
- Local scale probe: SQLite FTS5, **5000 spans**, **80 iterations**; p50 **2.4983705 ms**, p95 **3.398581 ms**, max **3.716504 ms**, top-1 **80/80**. This explicitly excludes PostgreSQL/network/concurrency/disk behavior. **ANCHORED_LOCAL**.
- Repository validation PASS: 1125 paths, 103 requirements, 99/99 audit findings classified. Infrastructure validation PASS: 135 requirements. Kubernetes base and production overlays PASS static topology validation only (19 resources each).

## 3. MINIMAL Δ — REMEDIATION

- **INF-EGRESS-001 [P1] FIXED_LOCAL** — LOCAL_ONLY performed a policy DNS resolution before httpx performed its own connection-time resolution, leaving a DNS-rebinding TOCTOU window. Remediation: LOCAL_ONLY now accepts only localhost or private/loopback IP literals and rejects arbitrary DNS names and link-local addresses fail-closed.
- **HTTP-BOUND-001 [P1] FIXED_LOCAL** — Billing callback size ceiling was checked after Request.body() buffered the complete attacker-controlled body. Remediation: Introduced streamed 64 KiB application boundary with early Content-Length refusal and cumulative chunk ceiling.
- **DEP-CONTRACT-001 [P1] FIXED_LOCAL** — pyproject declared pypdf <6 while the runtime lock pinned pypdf 6.14.2. Remediation: Declaration aligned to >=6.14,<7 and a gate now proves every declared runtime dependency accepts its exact lock version.
- **ASSURANCE-MUT-001 [P1] PARTIAL** — Uploaded mutation catalogue contained 21 targets no longer present in the current source plus one stale test citation; old mutation PASS could therefore certify obsolete call-sites. Remediation: All stale targets were re-anchored to current modules; catalogue now has 246 unique full IDs and structural reachability/cited-test gates pass. Changed-risk probe killed 23/23 mutants. Open: Fresh complete execution of all 246 mutants exceeded the available execution ceiling, so full mutation assurance remains unclosed.
- **TEST-NEG-001 [P1] FIXED_LOCAL** — ENOSPC reliability test monkeypatched a stale aggregate module and no longer struck the actual spool implementation. Remediation: Negative control now patches routes_corpus, restoring reachability of the failure path.
- **BUILD-IMPORT-001 [P1] FIXED_LOCAL** — snapshot_assurance.py failed when loaded via importlib file-spec because sibling release_identity was not importable. Remediation: Script directory is inserted explicitly before sibling import; existing module budget preserved.
- **ARTIFACT-OVERSIZE-001 [P1] FIXED_LOCAL** — A ~9.9 MiB candidate .bundle was shipped inside the source tree and violated the repository's own oversized-file invariant. Remediation: Removed candidate bundle from canonical source package; release evidence remains in reports rather than source-manifest scope.

### Source delta relative to uploaded ZIP

- Changed: `CONTRIBUTING.md`
- Changed: `SOURCE_MANIFEST.json`
- Changed: `apps/api/pyproject.toml`
- Changed: `apps/api/src/korpus/api/routes_billing_callbacks.py`
- Changed: `apps/api/src/korpus/application/egress.py`
- Changed: `apps/api/tests/test_gate_parity.py`
- Changed: `apps/api/tests/test_infrastructure_hardening.py`
- Changed: `apps/api/tests/test_model_egress.py`
- Changed: `apps/api/tests/test_reliability_degradation.py`
- Changed: `apps/api/tests/test_security_auth_api.py`
- Changed: `apps/api/tests/test_tenancy_api.py`
- Changed: `apps/api/tests/test_tenancy_threats.py`
- Changed: `config/operations/module-budget.json`
- Changed: `docs/operations/REQUIREMENTS_REGISTER.md`
- Changed: `scripts/run_mutation_tests.py`
- Changed: `scripts/snapshot_assurance.py`
- Added: `apps/api/src/korpus/api/request_limits.py`
- Deleted: `KORPUS_SYSTEM_v6.7.0_ACT006_CANDIDATE.bundle`

## 4. EVIDENCE

### Attack surface / reachability

- **authentication/session — LOCAL TESTED**. Vectors: JWT alg confusion, issuer/audience bypass, OIDC state/nonce/PKCE, cookie replay, CSRF. Identity dependency graph gate covers all non-public /v1 routes; existing tests enforce JWT/OIDC/session/CSRF boundaries.
- **tenant/data authorization — LOCAL TESTED / POSTGRES RLS EXTERNAL**. Vectors: IDOR, cross-account conversation access, self-granted role/corpus claims, disabled account reuse. Application-level foreign/invented IDs converge to 404 and entitlements intersect server-side identity. Real PostgreSQL RLS/dialect behavior requires container/CI evidence.
- **network egress — HARDENED + LOCAL TESTED**. Vectors: SSRF, DNS rebinding, cloud metadata, non-http schemes, egress leakage. LOCAL_ONLY now rejects arbitrary DNS and link-local; public/external posture remains governed by material classification.
- **untrusted documents/parsers — LOCAL STATIC/TESTED**. Vectors: zip bombs, parser command injection, oversized output, malicious PDF/DOCX. Parser subprocesses use argv arrays/no shell, scrubbed environment, temp cwd, resource/output limits and archive bounds. Container malware stack not executed here.
- **billing callbacks — HARDENED + LOCAL TESTED**. Vectors: oversized body, signature abuse, replay/idempotency. Streaming 64 KiB boundary added before complete buffering; signed callback endpoints remain explicit public exceptions to identity gate.
- **inference/RAG — LOCAL ADVERSARIAL TESTED / EXTERNAL RED TEAM OPEN**. Vectors: prompt injection, retrieval poisoning, planner leakage, tool abuse, evidence-boundary escape. Injection gate precedes retrieval; scope rechecked; planner text not trusted as evidence; hostile planner chaos case leaked no planner text.
- **deployment edge — STATIC VALIDATED**. Vectors: Host header, CORS, direct API exposure, network policy, service-account abuse. TrustedHost/CORS tests and Kubernetes topology validation pass; cluster execution and external penetration testing remain external.

### Dependency / supply-chain

- Exact Python lock inventory: **68 unique components**; artifact hashes present for **68/68**. Runtime lock SHA-256 `5bf7c9e99af26e445e6d12c12a817fe6b838377240939f06127ec586a1f06f98`; dev lock SHA-256 `b5028d055efc2d8f72be91c1e6efdd9f82203f2506a63865bff26e3489a6e6bc`. **ANCHORED_LOCAL**.
- Package metadata licenses resolved locally for **61/68**; unresolved because packages are not installed in this environment: ast-serialize, librt, mypy, mypy-extensions, psycopg, psycopg-binary, ruff. This is metadata inventory, not legal clearance.
- Targeted current advisory verification against GitHub Advisory Database shows the locked versions are at/after fixes for the listed PyJWT, python-multipart, Starlette, pypdf and cryptography advisories. See JSON report for exact advisory IDs and affected/fixed ranges.
- **Exhaustive CVE status = UNKNOWN.** `pip-audit`, OSV scanner, Trivy, Syft and equivalent scanners are absent; direct OSV API access failed because the execution environment cannot resolve `api.osv.dev`. No zero-CVE claim is made for the 68-component transitive set or OS/container layers.

### Assurance blockers

- `scripts/assemble_assurance.py`: FAIL — current `var/mutation-report.json` and `var/operational-gate.json` are absent.
- Quality gate: FAIL because the current interpreter has neither Ruff nor Mypy; this is missing-tool evidence, not a measured zero-defect result.
- Exact lock environment could not be reproduced from the execution package index; Docker/Podman are absent, so PostgreSQL/container behavior was not freshly executed.
- The uploaded ZIP has no `.git` metadata. A signed/tagged reproducible production release cannot be honestly created or attested from this snapshot.

## 5. RISKS / FAIL-MODES

- PostgreSQL RLS, dialect-specific transaction/concurrency behavior, HA/PITR, TLS/mTLS, cluster NetworkPolicy enforcement and container runtime hardening remain external evidence.
- Independent application/API/cloud penetration testing and RAG corpus-poisoning/evidence-boundary red team remain open.
- Full mutation execution remains open even though the catalogue is repaired and all changed-risk mutants tested here are killed.
- Existing promoted assurance artifacts must remain stale/failed until the complete evidence graph is regenerated; manually replacing source digests would create false assurance.

## EVAL-GATE

- **LOCAL REMEDIATION: PASS_WITH_CAVEATS**
- **PRODUCTION ASSURANCE / SIGNED RELEASE: FAIL**

Open gates: exact locked environment; complete 246-mutant run; fresh exhaustive dependency/CVE + container/OS SBOM scan; Ruff/Mypy; Docker/PostgreSQL execution; independent pentest; admissible TEVV; inference/RAG poisoning red-team; signed git-tagged reproducible release.
