SHELL := /bin/bash
PY := apps/api/.venv/bin/python
PIP := apps/api/.venv/bin/pip

.PHONY: deterministic-replay provenance provenance-verify reference-set reference-eval embedding-candidate-screen embedding-backfill corpus-admission gold-annotation-audit runtime-corpus-audit service-objectives corpus-release corpus-release-verify security-scan reproducible-build chaos-matrix ingestion-drill load-probe backup-sqlite restore-sqlite drive-snapshot drive-public serve-public public-tunnel draft-manifest import-corpus review-token audit-export web-contract web-contract-check environment-drift environment-observe requirements-register module-budget file-modes import-cycles release-identity source-manifest-verify retention-plan postgres-suite sqlite-recovery-drill quality-gate handoff-verify openapi audit-closure desired-state supply-chain-inventory kubernetes-validate github-actions-validate infra-validate backup-postgres restore-postgres api-install api-run api-test api-lint web-install web-run web-build bootstrap eval mutation migration-gate scale operational-gate assurance assemble-assurance snapshot audit-verify validate check release infra-secrets infra-up infra-support infra-down package clean production-engineering production-tevv production-observability production-state-contracts production-authorization production-redteam-internal production-redteam-external production-inference-security production-reliability-internal production-reliability production-postgres-security production-exact-environment production-sbom production-supply-chain production-mutation production-assurance production-assurance-verify production-release dependency-locks assurance-model-check standards-control-map slsa-provenance slsa-provenance-verify release-mutation-delta package-build-identity evidence-refresh mutation-probe coverage-ratchet coverage-union determinism-gate stress-gate plasticity-gate canonical-release-cycle production-hard-predicates military-readiness military-readiness-full

api-install:
	python3 -m venv apps/api/.venv
	$(PIP) install --no-deps --require-hashes --requirement apps/api/requirements.dev.lock

api-run:
	mkdir -p var/objects
	$(PY) -m uvicorn korpus.main:app --app-dir apps/api/src --host 127.0.0.1 --port 8000 --reload

# --cov-fail-under bounds one combined number. The release policy states line and
# branch minimums separately, and the only thing that read the branch one ran at the
# very end of the pipeline — so branch coverage sat below policy for as long as anyone
# had been writing tests. check_coverage_thresholds.py reads both from the policy.
api-test:
	PYTHONPATH=apps/api/src $(PY) -m pytest apps/api/tests --junitxml=var/pytest.xml --cov=apps/api/src/korpus --cov-branch --cov-report=term-missing --cov-report=xml:var/coverage.xml --cov-report=json:var/coverage.json --cov-fail-under=82
	PYTHONPATH=apps/api/src $(PY) scripts/check_coverage_thresholds.py

# The ratchet reads the union of both dialects, because both are what the suite runs.
# Measuring SQLite alone reports every `dialect.name == "postgresql"` arm as untaken by a
# run that cannot reach it — fourteen branches in `repository.py` alone — and the queue
# then lists work that is already done. `coverage-union` fails closed when the PostgreSQL
# report is absent rather than silently falling back to the SQLite one, so the number the
# ratchet reads always says which runs produced it.
coverage-ratchet: api-test coverage-union
	PYTHONPATH=apps/api/src:. $(PY) scripts/coverage_gap_plan.py --coverage var/coverage-union.json --out var/coverage-gap-plan.json

# The suite runs against both dialects; only one of them was ever measured. `api-test`
# measures SQLite, `postgres-suite` runs PostgreSQL with --no-cov, and eight
# `dialect.name` branches in the repository are therefore reported as untaken by a run
# that cannot reach them. This unions the two so the ratchet's own queue stops listing
# work that is already done — the ratchet itself keeps reading the SQLite report, which
# is the stricter of the two, so nothing is relaxed by producing this.
#   make coverage-union   (after api-test and a PostgreSQL run with coverage)
coverage-union:
	PYTHONPATH=apps/api/src $(PY) scripts/merge_dialect_coverage.py
	PYTHONPATH=apps/api/src:. $(PY) scripts/coverage_gap_plan.py --coverage var/coverage-union.json --out var/coverage-gap-plan-union.json

deterministic-replay:
	PYTHONPATH=apps/api/src:. $(PY) scripts/deterministic_replay_probe.py

determinism-gate:
	PYTHONPATH=apps/api/src:. $(PY) scripts/run_determinism_gate.py --out var/determinism-gate.json

stress-gate:
	PYTHONPATH=apps/api/src:. $(PY) scripts/run_stress_gate.py --out var/stress-gate.json

plasticity-gate:
	PYTHONPATH=apps/api/src:. $(PY) scripts/run_plasticity_gate.py --out var/plasticity-gate.json

# One serial fail-closed release cycle. The explicit recursive makes keep this order
# even when the parent make is invoked with -j; no later gate can hide an earlier FAIL.
# `mutation` moved ahead of `operational-gate` on 2026-08-28. The gate reads
# MUTATION_REPORT.json and refuses a report generated from another source tree, so with
# mutation last the gate always read the *previous* run's report: on any changed tree the
# cycle failed with `mutation: generated from a different source tree`, and passed only
# when it was run twice. Producers before the gate that consumes them.
canonical-release-cycle:
	$(MAKE) api-lint PY=$(PY)
	$(MAKE) coverage-ratchet PY=$(PY)
	$(MAKE) determinism-gate PY=$(PY)
	$(MAKE) stress-gate PY=$(PY)
	$(MAKE) plasticity-gate PY=$(PY)
	$(MAKE) release-mutation-delta PY=$(PY)
	$(MAKE) eval PY=$(PY)
	$(MAKE) mutation PY=$(PY)
	$(MAKE) migration-gate PY=$(PY)
	$(MAKE) scale PY=$(PY)
	$(MAKE) operational-gate PY=$(PY)
	$(MAKE) validate PY=$(PY)
	$(MAKE) web-build

# `mypy apps/api/src` from the repository root did not type-check this project.
# The [tool.mypy] section lives in apps/api/pyproject.toml, and mypy only reads a
# pyproject.toml it finds in the *current* directory — so the strict flags were never
# applied. Passing a source path also overrode packages = ["korpus"], which left mypy
# unable to resolve korpus.* at all: the run reported 136 import-not-found errors
# instead of the 42 real strict violations underneath them (probed 2026-08-03).
# Runs both tools and records the run in var/quality-report.json. The aggregate
# assurance verdict requires that recording: a declared-but-unexecuted tool used to
# sit next to "status": "PASS" (destruction stage 2026-08-03).
api-lint:
	PYTHONPATH=apps/api/src $(PY) scripts/run_quality_gate.py

web-install:
	npm --prefix apps/web ci

web-run:
	npm --prefix apps/web run dev

# `node --check <file>` exits 0 for any file containing an `import`, so the two
# --check invocations that used to stand here stopped checking anything the moment
# app.js became a module and kept printing success. The parse now happens inside
# validate.mjs, on stdin, with an explicit --input-type — and validate_gate.test.mjs
# mutates a copy of the tree to prove each control can still fail.
web-build: web-contract-check
	npm --prefix apps/web run lint
	npm --prefix apps/web run test
	npm --prefix apps/web run build
	npm --prefix apps/web run test:browser

# Generated browser contracts: operator request constraints and the consumer transport
# surface. Both derive from canonical OpenAPI/release identity; neither is hand-maintained.
web-contract:
	PYTHONPATH=apps/api/src $(PY) scripts/generate_web_contract.py
	PYTHONPATH=apps/api/src $(PY) scripts/generate_transport_contract.py

web-contract-check:
	PYTHONPATH=apps/api/src $(PY) scripts/generate_web_contract.py --check
	PYTHONPATH=apps/api/src $(PY) scripts/generate_transport_contract.py --check

# OPS-004. Two commands, because the observation has to be taken on the machine that is
# running and the comparison made against the manifest as committed. Doing both here
# would fingerprint the build host, which is the failure the check exists to catch.
environment-drift:
	$(PY) scripts/check_environment_drift.py --observation "$(OBSERVATION)"

environment-observe:
	$(PY) scripts/check_environment_drift.py --observe "$(ROOT)" --out "$(OUT)"

bootstrap:
	mkdir -p var/objects
	PYTHONPATH=apps/api/src $(PY) scripts/bootstrap_local.py

eval:
	PYTHONPATH=apps/api/src $(PY) scripts/run_evals.py

# A measurement, not a gate. The curated catalogue covers 126 modules and reports 100%
# over itself; 162 modules and 15 853 lines carry no mutant at all, so that number says
# nothing about them. This samples ordinary operator mutations there — a comparison
# flipped, a boolean swapped — and reports what the suite kills. Survivors are candidates
# for the curated catalogue, not defects on their own: an equivalent mutation is always a
# possible explanation and has to be checked one at a time.
#   make mutation-probe SAMPLE=60
mutation-probe:
	PYTHONPATH=apps/api/src $(PY) scripts/probe_uncatalogued_mutation.py \
	  $(if $(SAMPLE),--sample $(SAMPLE)) $(if $(SEED),--seed $(SEED))

mutation:
	PYTHONPATH=apps/api/src PYTHON=$(PY) KORPUS_MUTATION_SHARDS=6 scripts/run_mutation_shards.sh

# The suite against a migrated PostgreSQL database, in a throwaway container. Not part
# of `check`: it needs docker, and `check` has to run where docker does not. It is a
# required CI job instead — the closures in this tree were proved on SQLite, and the
# two dialects have separate implementations of the currency filters, the retrieval
# projection and the audit head update.
postgres-suite:
	scripts/run_postgres_suite.sh

migration-gate:
	PYTHONPATH=apps/api/src $(PY) scripts/run_migration_gate.py

scale:
	PYTHONPATH=apps/api/src $(PY) scripts/run_scale_probe.py

operational-gate:
	PYTHONPATH=apps/api/src $(PY) scripts/run_operational_gate.py

military-readiness:
	PYTHONPATH=apps/api/src:. $(PY) scripts/run_military_readiness_campaign.py

military-readiness-full:
	PYTHONPATH=apps/api/src:. $(PY) scripts/run_military_readiness_campaign.py --full --full-timeout 180 --regression-batch-size 8 --regression-workers 2

assemble-assurance:
	PYTHONPATH=apps/api/src $(PY) scripts/assemble_assurance.py

assurance:
	PYTHONPATH=apps/api/src $(PY) scripts/run_research_assurance.py

snapshot:
	PYTHONPATH=apps/api/src $(PY) scripts/snapshot_assurance.py

# A plan, not a scheduler: it computes dispositions and deletes nothing. Exit 2 means
# material is past its retention period with no deletion permission, or sits in a
# corpus with no governance policy — decisions nobody has made, not code faults.
# A ratchet, not a target: modules may shrink freely, growth fails. "Not yet in the
# budget" is how a file gets to two thousand lines without anyone noticing.
# The register as a document: §2.5 asks an outside party to judge this system, and the
# first thing they need is the list of properties it claims about itself.
requirements-register:
	PYTHONPATH=apps/api/src $(PY) scripts/export_requirements.py

import-cycles:
	PYTHONPATH=apps/api/src $(PY) scripts/check_import_cycles.py

release-identity:
	PYTHONPATH=apps/api/src $(PY) scripts/check_release_identity.py

source-manifest-verify:
	PYTHONPATH=scripts python3 scripts/verify_source_manifest.py


package-build-identity:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/verify_package_build_identity.py

release-mutation-delta:
	PYTHONPATH=apps/api/src:. $(PY) scripts/run_release_mutation_microcampaign.py

# The report is written twice on purpose. `var/` is the run artefact; the copy under
# `reports/` is what `current-truth-verify` reads to prove the evidence is bound to the
# tree that produced it. Copying it here rather than by hand is why the two stopped
# disagreeing: the checked-in copy had been four source digests behind for weeks, and
# nothing in the pipeline updated it.
dependency-locks:
	mkdir -p var
	PYTHONPATH=apps/api/src:. $(PY) scripts/verify_dependency_locks.py --out var/dependency-lock-report.json --osv-out var/osv-query-batch.json
	install -m 0644 var/dependency-lock-report.json reports/DEPENDENCY_LOCK_VERIFICATION_CURRENT.json

assurance-model-check:
	mkdir -p var
	PYTHONPATH=apps/api/src:. $(PY) scripts/model_check_assurance.py > var/assurance-model-check.json

standards-control-map:
	mkdir -p var
	PYTHONPATH=apps/api/src:. $(PY) scripts/verify_standards_control_map.py --out var/standards-control-map-verification.json
	install -m 0644 var/standards-control-map-verification.json reports/STANDARDS_CONTROL_MAP_VERIFICATION.json

# Artifact provenance is intentionally emitted beside the ZIP rather than embedded in it:
# the statement binds the completed artifact digest, and embedding it would create a
# circular digest. Local provenance is structurally verifiable but does not self-assert
# a SLSA level or trusted builder identity.
slsa-provenance:
	test -n "$(ARTIFACT)"
	test -n "$(OUT)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/slsa_provenance.py generate --artifact "$(ARTIFACT)" --out "$(OUT)" $(if $(BUILDER_ID),--builder-id "$(BUILDER_ID)") $(if $(INVOCATION_ID),--invocation-id "$(INVOCATION_ID)")

slsa-provenance-verify:
	test -n "$(ARTIFACT)"
	test -n "$(STATEMENT)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/slsa_provenance.py verify --artifact "$(ARTIFACT)" --statement "$(STATEMENT)" --trusted-builders config/assurance/trusted-builders.v1.json $(if $(REQUIRE_TRUSTED_BUILDER),--require-trusted-builder)

module-budget:
	PYTHONPATH=apps/api/src $(PY) scripts/check_module_budget.py

# Ruff states the same rule as EXE001/EXE002, but it reads only Python under four
# directories: the shell scripts, Dockerfiles, Terraform and manifests had no mode check
# at all. This reads `git ls-files`, which is the set the source manifest hashes.
file-modes:
	$(PY) scripts/check_file_modes.py

# The doctrine catalog's provenance rules, executable: RESTRICTED never ingestible,
# rights clearance stays a human decision, secondary analysis is never given a governing
# authority, an unverified mirror enters quarantine. A curated bibliography, not corpus
# bytes — gated so a hand-edit that would let a restricted or commercial source in fails.
doctrine-catalog:
	PYTHONPATH=apps/api/src $(PY) scripts/validate_doctrine_catalog.py

retention-plan:
	PYTHONPATH=apps/api/src $(PY) scripts/plan_retention.py

# AUD-004's executable half. The closure register cited this script as evidence and
# nothing ran it — a citation that names a file rather than a run, which is the shape
# ADR-0008 exists to refuse. `--limit 0` makes it a smoke run against whatever chain is
# present: the batch is empty, and an empty batch is the ordinary case, not a failure.
# A review session over a LAN: the real nginx edge, the API in jwt mode, a short-lived
# token. `auth_mode=dev` trusts whoever connects and is refused on any non-loopback bind
# for exactly that reason, so showing this to people who are not at this keyboard needs
# a signed token rather than a wider bind.
#
# In jwt mode the token *carries* the entitlements — the server-side profile projects
# identity only under oidc, which controlled environments require. Whoever holds the
# token holds what is written in it, which is why it is short-lived and why the secret
# is mode 600.
# Bring a directory of documents into the corpus. Every version lands in quarantine:
# approval is a person taking responsibility in the audit chain under their own name,
# and a bulk importer that granted it would forge that signature at scale.
#   make import-corpus MANIFEST=path/to/manifest.json
# Pull a Drive folder into a local snapshot with provenance. One-time setup on the
# operator's own hands: `rclone config` -> new remote named `drive`, type `drive`,
# scope 2 (read-only). Fetching is not ingestion: a live dependency would let a document
# change after it was reviewed.
#   make drive-snapshot FOLDER_ID=... INTO=var/corpus/ml
drive-snapshot:
	$(PY) scripts/fetch_drive_snapshot.py --remote $(or $(REMOTE),drive:) \
	  --folder-id "$(FOLDER_ID)" --into "$(or $(INTO),var/corpus)"

# The same snapshot, for a folder shared with "anyone with the link". No OAuth, no
# account, no rclone: Drive's own web viewer reads such a folder through a browser key
# the folder page carries, and this asks the same question the same way. A folder that
# is not public simply does not answer.
#   make drive-public FOLDER_ID=... INTO=var/corpus/ml MAX_FILE_BYTES=2000000
drive-public:
	$(PY) scripts/fetch_drive_public.py --folder-id "$(FOLDER_ID)" \
	  --into "$(or $(INTO),var/corpus)" \
	  $(if $(MAX_FILE_BYTES),--max-file-bytes $(MAX_FILE_BYTES)) $(if $(LIMIT),--limit $(LIMIT))

# Publish the read-only reader on a public edge that authenticates on the visitor's
# behalf. Everything reachable through it is public by decision, not by default.
#   make serve-public
serve-public:
	bash scripts/serve_public.sh

# Keep a public HTTPS address pointed at the edge, and write the current one to
# var/public/URL. The provider assigns the hostname per session and rotates it on every
# reconnect, so the file is the address of record and an empty file means there is none.
#   make public-tunnel
public-tunnel:
	bash scripts/public_tunnel.sh

# Draft a manifest from a fetched directory. Everything it cannot read from a filename —
# issuer, revision, publication date — is marked REVIEW_REQUIRED, and import-corpus
# refuses those entries.
#   make draft-manifest ROOT=var/corpus/ml OUT=var/corpus/ml/manifest.json
draft-manifest:
	$(PY) scripts/build_import_manifest.py --root "$(ROOT)" --out "$(OUT)" \
	  $(if $(ISSUER),--issuer "$(ISSUER)") $(if $(AUTHORITY),--authority "$(AUTHORITY)") \
	  $(if $(FROM_SNAPSHOT),--from-snapshot)

import-corpus:
	PYTHONPATH=apps/api/src $(PY) scripts/import_corpus.py --manifest "$(MANIFEST)" $(IMPORT_FLAGS)

corpus-admission:
	test -n "$(MANIFEST)"
	test -n "$(ROOT)"
	PYTHONPATH=apps/api/src $(PY) scripts/audit_corpus_admission.py --manifest "$(MANIFEST)" --root "$(ROOT)" $(if $(OUT),--out "$(OUT)")

gold-annotation-audit:
	test -n "$(LEDGER)"
	PYTHONPATH=apps/api/src $(PY) scripts/audit_gold_annotations.py --ledger "$(LEDGER)" $(if $(OUT),--out "$(OUT)")

review-token:
	PYTHONPATH=apps/api/src $(PY) scripts/mint_review_token.py \
	  --subject $(or $(SUBJECT),reviewer) \
	  --minutes $(or $(MINUTES),120) \
	  --roles $(or $(ROLES),user) \
	  --clearance $(or $(CLEARANCE),public) \
	  --corpora $(or $(CORPORA),public)

audit-export:
	PYTHONPATH=apps/api/src $(PY) scripts/export_audit.py --limit $(or $(LIMIT),1000)

audit-verify:
	PYTHONPATH=apps/api/src $(PY) scripts/verify_audit.py

handoff-verify:
	PYTHONPATH=apps/api/src $(PY) scripts/verify_handoff_contract.py


openapi:
	PYTHONPATH=apps/api/src $(PY) scripts/openapi_contract.py

audit-closure:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/build_audit_closure.py

desired-state:
	python3 scripts/generate_desired_state.py --check

# $(PY), not python3: this reads license metadata from the installed distributions, so
# a bare interpreter resolves whichever packages happen to be on the system — five of
# sixty-eight, when this was written. The lock is the environment it must be asked in.
supply-chain-inventory:
	PYTHONPATH=apps/api/src $(PY) scripts/generate_supply_chain_inventory.py

kubernetes-validate:
	python3 scripts/validate_kubernetes.py

github-actions-validate:
	PYTHONPATH=apps/api/src $(PY) scripts/validate_github_actions.py

.PHONY: public-web-deploy
public-web-deploy:
	$(PY) scripts/deploy_public_web.py

.PHONY: public-watchdog-install public-health
public-watchdog-install:
	python3 scripts/install_public_watchdog.py

public-health:
	python3 scripts/public_health_controller.py --observe-only

# audit-closure is deliberately NOT here: it resolves citations that include
# var/mutation-report.json, which `mutation` produces. As a prerequisite of `validate`
# it ran first and passed only on a tree where an earlier run had left the file behind.
validate: handoff-verify openapi desired-state supply-chain-inventory dependency-locks assurance-model-check standards-control-map import-cycles release-identity module-budget file-modes requirements-register doctrine-catalog github-actions-validate production-hard-predicates
	python3 scripts/validate_repository.py --context FULL_SSOT_DISTRIBUTION
	python3 scripts/validate_infrastructure.py
	python3 scripts/validate_kubernetes.py

infra-validate:
	python3 scripts/validate_infrastructure.py

backup-postgres:
	scripts/backup_postgres.sh

restore-postgres:
	scripts/restore_postgres.sh "$(BACKUP)"

# The deployment that is actually serving holds its corpus in SQLite: 1616 documents and
# 116 229 spans that took five hours to build, on one disk with no replica. `VACUUM INTO`
# takes a consistent snapshot while the reader is served; the object store travels with
# it, because a corpus database without the objects it names restores to a system that
# cites passages nobody can open.
#   KORPUS_BACKUP_ENCRYPTION_KEY_FILE=... KORPUS_BACKUP_KEY_ID=... make backup-sqlite
sqlite-recovery-drill:
	PYTHONPATH=apps/api/src:scripts PYTHON=$(PY) scripts/run_sqlite_recovery_drill.sh

backup-sqlite:
	scripts/backup_sqlite.sh

# Load, spike and soak against a running deployment, with the conditions recorded beside
# the numbers. SRE-005 and RAG-014 both say the same thing: scale evidence produced
# against a fixture is evidence about the fixture.
#   make load-probe BASE=http://127.0.0.1:8000 TOKEN=...
# Break each dependency in turn and record what the system says. A fail-closed claim is a
# claim about behaviour under failure, and this tree had tested every dependency present
# and none absent.
# Every scanner the pipeline declares, run here, with the reports archived beside their
# exit codes. A declared scanner is a plan; an archived report is evidence.
# Freeze what the corpus contains and sign it, so a citation can be traced to the release
# it came from without the running system. Verifying against a restored backup is how a
# rollback is proved to have landed.
#   make corpus-release OUT=var/releases/$(shell date +%F).json SIGNER="..."
corpus-release:
	$(PY) scripts/corpus_release.py freeze --out "$(OUT)" \
	  $(if $(DATABASE),--database "$(DATABASE)") $(if $(SIGNER),--signer "$(SIGNER)") \
	  $(if $(KEY_FILE),--key-file "$(KEY_FILE)")

corpus-release-verify:
	$(PY) scripts/corpus_release.py verify --manifest "$(MANIFEST)" \
	  $(if $(DATABASE),--database "$(DATABASE)") $(if $(KEY_FILE),--key-file "$(KEY_FILE)")

# What this deployment promises, checked against what it was measured doing. An objective
# nobody checks is a paragraph.
# Freeze a reference set from the deployed corpus, stratified and digest-sealed, and run
# it. Objective on retrieval, citation integrity and refusal; silent on whether an answer
# is good, which needs annotators (RAG-003).
#   make reference-set && make reference-eval TOKEN=...
# Say what an image was built from, sign it, and refuse to deploy what does not verify.
# An SBOM travelling beside an image answers "what is in some image".
#   make provenance IMAGE=korpus-api:local OUT=var/provenance/api.json
provenance:
	$(PY) scripts/build_provenance.py attest --image "$(IMAGE)" --out "$(OUT)" \
	  $(if $(SBOM),--sbom "$(SBOM)") $(if $(KEY_FILE),--key-file "$(KEY_FILE)")

provenance-verify:
	$(PY) scripts/build_provenance.py verify --statement "$(STATEMENT)" \
	  $(if $(IMAGE),--image "$(IMAGE)") $(if $(SBOM),--sbom "$(SBOM)") \
	  $(if $(KEY_FILE),--key-file "$(KEY_FILE)")

reference-set:
	$(PY) scripts/build_reference_set.py $(if $(DATABASE),--database "$(DATABASE)")

reference-eval:
	$(PY) scripts/run_reference_eval.py $(if $(BASE),--base "$(BASE)") $(if $(TOKEN),--token "$(TOKEN)")

embedding-candidate-screen:
	$(PY) scripts/run_embedding_candidate_screen.py

embedding-backfill:
	PYTHONPATH=apps/api/src $(PY) scripts/run_embedding_backfill.py

runtime-corpus-audit:
	@test -n "$(DATABASE)" || { echo "DATABASE is required" >&2; exit 64; }
	$(PY) scripts/audit_runtime_corpus.py --database "$(DATABASE)" \
	  $(if $(OBJECT_ROOT),--object-root "$(OBJECT_ROOT)") $(if $(OUT),--out "$(OUT)")

service-objectives:
	$(PY) scripts/service_objectives.py $(if $(MEASUREMENTS),--measurements "$(MEASUREMENTS)")

# Backup copies, evidence retention and quotas, checked against the disk. A policy in a
# document is a sentence.
retention-policy:
	$(PY) scripts/retention_policy.py

# Gate reports kept under their digest for the system's life, not the pipeline's.
evidence-registry:
	$(PY) scripts/evidence_registry.py

# How long a known vulnerability may stay here, and whether the scan that would find it
# actually ran. A scanner that exited 127 is neither clean nor a finding.
patch-policy:
	$(PY) scripts/patch_policy.py

security-scan:
	scripts/security_scan.sh

# Build twice from one tree and say which layers disagree. The recorded nondeterminism is
# the part usually skipped, and skipping it is how "reproducible" becomes a word.
reproducible-build:
	scripts/reproducible_build_probe.sh

chaos-matrix:
	PYTHONPATH=.:apps/api/src $(PY) scripts/chaos_matrix.py

# Kill a corpus import partway and prove the resumed run reconciles by content with an
# uninterrupted one. "Resumable" was a property of the design until this executed it.
#   make ingestion-drill MANIFEST=var/corpus/ml-manifest.json ROOT=var/corpus/ml
ingestion-drill:
	$(PY) scripts/ingestion_recovery_drill.py --manifest "$(MANIFEST)" --root "$(ROOT)" \
	  --workdir "$(or $(WORKDIR),var/drill)" $(if $(DOCUMENTS),--documents $(DOCUMENTS))

load-probe:
	$(PY) scripts/load_probe.py $(if $(BASE),--base "$(BASE)") $(if $(TOKEN),--token "$(TOKEN)") \
	  $(if $(CONCURRENCY),--concurrency $(CONCURRENCY)) $(if $(SPIKE),--spike $(SPIKE))

# Restores somewhere else on purpose: a drill that overwrites the live corpus is a drill
# nobody runs, and one that never runs is not known to work.
#   make restore-sqlite BACKUP=var/backups/sqlite/korpus-<stamp>.tar.enc INTO=var/restored
restore-sqlite:
	scripts/restore_sqlite.sh "$(BACKUP)" "$(or $(INTO),var/restored)"

check: validate api-test api-lint eval mutation audit-closure migration-gate scale operational-gate web-build

release: assurance snapshot validate package

infra-secrets:
	bash scripts/init_local_secrets.sh

infra-up: infra-secrets
	docker compose up -d --wait web worker

infra-support: infra-secrets
	docker compose up -d --wait postgres minio otel-collector migrate minio-init

infra-down:
	docker compose down

package:
	bash scripts/package_repository.sh

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml var dist apps/web/dist apps/web/.next

# Production assurance is deliberately separate from local research assurance.
# These targets generate evidence; the final assembler still fails unless every
# required gate is current, release-bound and of the required evidence class.
production-engineering:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_engineering_production_gate.py

production-tevv:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_tevv_production_gate.py

production-observability:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/verify_observability_contract.py

production-state-contracts:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/export_state_contracts.py

production-authorization:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/export_authorization_matrix.py

production-redteam-internal:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_pytest_campaign.py config/assurance/redteam-internal-v1.json

production-redteam-external:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/validate_external_redteam_evidence.py

production-inference-security:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_inference_security_gate.py

production-reliability-internal:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_pytest_campaign.py config/assurance/reliability-internal-v1.json

production-reliability:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_reliability_gate.py

production-postgres-security:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_postgres_security_gate.py

production-exact-environment:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_exact_environment_gate.py

production-hard-predicates:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/verify_production_hard_predicates.py

production-sbom:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/generate_lock_sbom.py

production-supply-chain: dependency-locks
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/build_supply_chain_evidence_manifest.py
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_supply_chain_gate.py

production-mutation:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_mutation_production_gate.py

production-assurance:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/assemble_production_assurance.py

production-assurance-verify:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/verify_production_assurance.py

production-release: production-assurance
	test -n "$(KORPUS_PRODUCTION_ASSURANCE_SIGNING_KEY)"
	test -n "$$KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256"
	test -n "$$KORPUS_TRUSTED_RELEASE_SIGNER_SHA256"
	test "$$KORPUS_TRUSTED_PRODUCTION_ASSURANCE_SIGNER_SHA256" != "$$KORPUS_TRUSTED_RELEASE_SIGNER_SHA256"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/release_attestation.py sign --manifest reports/PRODUCTION_ASSURANCE_REPORT.json --key "$(KORPUS_PRODUCTION_ASSURANCE_SIGNING_KEY)" --out reports/PRODUCTION_ASSURANCE_REPORT.attestation.json
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/verify_production_assurance.py
	KORPUS_RELEASE_SIGNING_KEY="$(KORPUS_RELEASE_SIGNING_KEY)" scripts/package_production_release.sh

# Zero-install security floor. This deliberately supplements rather than replaces
# networked secret/dependency/container scanners.
builtin-security:
	mkdir -p var
	PYTHONPATH=apps/api/src:. $(PY) scripts/run_builtin_security_gate.py --out var/builtin-security-gate.json

# Aggregate what this checkout can prove while preserving external production blockers.
local-production-preflight:
	mkdir -p var
	PYTHONPATH=apps/api/src:. $(PY) scripts/run_local_production_preflight.py --out var/local-production-preflight.json

# Canonical v0.8 assurance/release tooling entry points.
readiness-evaluate:
	PYTHONPATH=apps/api/src:. $(PY) scripts/evaluate_engineering_readiness.py --evidence "$(EVIDENCE)" $(if $(OUT),--out "$(OUT)")

release-truth: production-hard-predicates
	PYTHONPATH=apps/api/src:. $(PY) scripts/generate_release_truth.py

# Order matters and used to be tribal knowledge. Every target that writes into `reports/`
# changes the source digest, which invalidates the bindings written before it, so running
# `release-truth` first and `dependency-locks` second leaves current-truth failing on two
# reports that were correct when they were produced. This is the order that terminates:
# the inputs first, the bindings over them last.
evidence-refresh:
	$(MAKE) dependency-locks PY=$(PY)
	$(MAKE) standards-control-map PY=$(PY)
	$(MAKE) release-truth PY=$(PY)
	PYTHONPATH=scripts $(PY) scripts/generate_manifest.py --kind source
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/sync_package_build_identity.py
	$(MAKE) current-truth-verify PY=$(PY)

current-truth-verify:
	PYTHONPATH=apps/api/src:. $(PY) scripts/verify_current_truth.py $(if $(OUT),--out "$(OUT)")

regression-carry-forward-verify:
	PYTHONPATH=apps/api/src:. $(PY) scripts/verify_regression_carry_forward.py $(if $(POLICY),--policy "$(POLICY)") $(if $(OUT),--out "$(OUT)")

zip-safety-verify:
	@test -n "$(ARCHIVE)" || (echo "ARCHIVE is required" >&2; exit 2)
	PYTHONPATH=apps/api/src:. $(PY) scripts/zip_safety.py "$(ARCHIVE)"

# Release graph entrypoints: support modules are imported by these executable runners.
full-ssot-package:
	PYTHONPATH=apps/api/src:scripts:. $(PY) scripts/package_full_ssot.py $(if $(OUT),--out "$(OUT)")

external-gate-campaign:
	PYTHONPATH=apps/api/src:scripts:. $(PY) scripts/run_external_gate_campaign.py

gcp-production-contract:
	PYTHONPATH=apps/api/src:scripts:. $(PY) scripts/verify_gcp_production.py --output reports/GCP_PRODUCTION_CONTRACT.json

gcp-slo-contract:
	PYTHONPATH=apps/api/src:scripts:. $(PY) scripts/verify_gcp_slo.py --output reports/GCP_SLO_CONTRACT.json

# Predictive Evidence Control (PEC / DGC-v2).
# These targets intentionally do not supply production thresholds, corpus identities,
# or evaluator decisions. Missing evidence is a failed/unknown admission, not a default.
.PHONY: pec-dataset-build pec-dataset-audit pec-replay pec-oracle pec-decision-sensitivity pec-train pec-export pec-verify pec-ablation pec-metamorphic pec-research pec-promote pec-protocol-check

PEC_DATASET ?= evals/datasets/pec/pec_eval.jsonl
PEC_REPLAY ?= reports/PEC_COUNTERFACTUAL_REPLAY_CURRENT.json
PEC_ORACLE ?= reports/PEC_ORACLE_CURRENT.json
PEC_PROFILE ?= config/pec/controller-candidate.json

pec-dataset-build:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/build_pec_eval_dataset.py --source evals/datasets/reference.jsonl --out $(PEC_DATASET) --receipt reports/PEC_DATASET_BUILD_CURRENT.json

pec-dataset-audit:
	test -n "$(VERSION_INVENTORY)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/audit_pec_eval_dataset.py --dataset $(PEC_DATASET) --version-inventory "$(VERSION_INVENTORY)" $(if $(PRODUCTION_JUDGED),--production-judged) --release-gate --out reports/PEC_DATASET_AUDIT_CURRENT.json

pec-replay:
	test -n "$(PEC_RUNNER)$(PEC_OBSERVATIONS)"
	test -n "$(CORPUS_RELEASE_ID)"
	test -n "$(ANSWER_CALIBRATION_ID)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_counterfactual_replay.py --dataset $(PEC_DATASET) $(if $(PEC_RUNNER),--runner "$(PEC_RUNNER)",--observations "$(PEC_OBSERVATIONS)") --corpus-release-id "$(CORPUS_RELEASE_ID)" --answer-calibration-id "$(ANSWER_CALIBRATION_ID)" --evaluation-protocol evals/EVALUATION_PROTOCOL.md --release-gate --out $(PEC_REPLAY)

pec-oracle:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/solve_pec_oracle.py --replay $(PEC_REPLAY) --release-gate --out $(PEC_ORACLE)

pec-decision-sensitivity:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_pec_decision_sensitivity_campaign.py --oracle $(PEC_ORACLE) --release-gate --out reports/PEC_DECISION_SENSITIVITY_CURRENT.json

pec-train:
	test -n "$(PEC_RISK_LIMIT)"
	test -n "$(PEC_MIN_LEAF_SAMPLES)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/train_pec_controller.py --dataset $(PEC_DATASET) --oracle $(PEC_ORACLE) --risk-limit "$(PEC_RISK_LIMIT)" --minimum-leaf-samples "$(PEC_MIN_LEAF_SAMPLES)" --release-gate --out reports/PEC_TRAINING_CURRENT.json

pec-export:
	test -n "$(CORPUS_RELEASE_ID)"
	test -n "$(ANSWER_CALIBRATION_ID)"
	test -n "$(PEC_PROFILE_ID)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/export_pec_controller.py --training reports/PEC_TRAINING_CURRENT.json --oracle $(PEC_ORACLE) --dataset $(PEC_DATASET) --system-manifest SOURCE_MANIFEST.json --evaluation-protocol evals/EVALUATION_PROTOCOL.md --replay-receipt $(PEC_REPLAY) --corpus-release-id "$(CORPUS_RELEASE_ID)" --answer-calibration-id "$(ANSWER_CALIBRATION_ID)" --profile-id "$(PEC_PROFILE_ID)" --out $(PEC_PROFILE) --receipt reports/PEC_EXPORT_CURRENT.json --release-gate

pec-verify:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/verify_pec_controller.py --profile $(PEC_PROFILE) --dataset $(PEC_DATASET) --system-manifest SOURCE_MANIFEST.json --evaluation-protocol evals/EVALUATION_PROTOCOL.md --replay-receipt $(PEC_REPLAY) --training-receipt reports/PEC_TRAINING_CURRENT.json --oracle $(PEC_ORACLE) --release-gate --out reports/PEC_CONTROLLER_VERIFY_CURRENT.json

pec-ablation:
	test -n "$(PEC_BASELINE_OBSERVATIONS)"
	test -n "$(PEC_CANDIDATE_OBSERVATIONS)"
	test -n "$(PEC_MIN_INFORMATIVE_PAIRS)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_pec_ablation_campaign.py --baseline baseline="$(PEC_BASELINE_OBSERVATIONS)" --candidate pec="$(PEC_CANDIDATE_OBSERVATIONS)" --required-candidate pec --minimum-informative-pairs "$(PEC_MIN_INFORMATIVE_PAIRS)" --release-gate --out reports/PEC_ABLATION_CURRENT.json

pec-metamorphic:
	test -n "$(PEC_METAMORPHIC_OBSERVATIONS)"
	test -n "$(PEC_MIN_METAMORPHIC_PAIRS)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_pec_metamorphic_campaign.py --observations "$(PEC_METAMORPHIC_OBSERVATIONS)" --minimum-pairs "$(PEC_MIN_METAMORPHIC_PAIRS)" --release-gate --out reports/PEC_METAMORPHIC_CURRENT.json

pec-research:
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_pec_research_program.py --dataset $(PEC_DATASET) $(if $(wildcard $(PEC_REPLAY)),--replay $(PEC_REPLAY)) $(if $(wildcard $(PEC_ORACLE)),--oracle $(PEC_ORACLE)) --out reports/PEC_RESEARCH_PROGRAM_CURRENT.json

pec-promote:
	test -n "$(PEC_APPROVED_BY)"
	test -n "$(PEC_CHANGE_ID)"
	test -n "$(PEC_EVIDENCE_ARGS)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/promote_pec_profile.py --profile $(PEC_PROFILE) $(PEC_EVIDENCE_ARGS) --approved-by "$(PEC_APPROVED_BY)" --change-id "$(PEC_CHANGE_ID)" --out config/pec/promoted-controller.json --receipt reports/PEC_PROMOTION_CURRENT.json

pec-protocol-check:
	PYTHONPATH=apps/api/src:scripts $(PY) -m pytest -q apps/api/tests/test_decision_sensitivity.py apps/api/tests/test_pec_protocol_gates.py apps/api/tests/test_pec_replay.py apps/api/tests/test_pec_training.py apps/api/tests/test_pec_integration.py apps/api/tests/test_pec_observability.py
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/check_module_budget.py

.PHONY: pec-contextual-benchmark
pec-contextual-benchmark:
	test -n "$(PEC_CONTEXTUAL_OBSERVATIONS)"
	test -n "$(PEC_MIN_CONTEXTUAL_PAIRS)"
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/run_pec_contextual_benchmark.py --observations "$(PEC_CONTEXTUAL_OBSERVATIONS)" --minimum-informative-pairs "$(PEC_MIN_CONTEXTUAL_PAIRS)" --release-gate --out reports/PEC_CONTEXTUAL_BENCHMARK_CURRENT.json

.PHONY: regression-shard regression-shard-merge backend-report release-evidence
REGRESSION_SHARDS ?= 24
REGRESSION_TIMEOUT ?= 240
regression-shard:
	test -n "$(SHARD_INDEX)"
	mkdir -p reports/regression/shards
	PYTHONPATH=apps/api/src:scripts:. $(PY) scripts/run_regression_shards.py run --shard-index "$(SHARD_INDEX)" --shard-count "$(REGRESSION_SHARDS)" --timeout-seconds "$(REGRESSION_TIMEOUT)" --out "reports/regression/shards/shard-$(SHARD_INDEX).json"

regression-shard-merge:
	PYTHONPATH=apps/api/src:scripts:. $(PY) scripts/run_regression_shards.py merge --out reports/regression/FULL_REGRESSION_CURRENT.json reports/regression/shards/shard-*.json

# The whole sharded regression, merged, and projected into the report the preflight reads.
# `FULL_BACKEND_REPORT.json` had no producer: the copy in the tree cites a path from an
# ad-hoc run, so the preflight has been reading a stale artefact and failing all eleven of
# its local checks on binding rather than on substance.
# Every report the preflight reads, produced against this tree and then published.
# `run_local_production_preflight.py` requires eleven reports under `reports/release/<tag>/`
# and each of them is produced by a target here — but nothing carried them across, so the
# copies in that directory were placed by hand and predated the tree they described. The
# preflight's eleven local failures were entirely about staleness.
#
# Order is the whole content of this target: producers first, coverage before its gap
# plan, and the publication last, after the digest has stopped moving. An artefact bound
# to another tree is refused by the publisher rather than copied.
release-evidence:
	$(MAKE) api-test PY=$(PY)
	$(MAKE) coverage-union PY=$(PY)
	$(MAKE) coverage-ratchet PY=$(PY)
	$(MAKE) determinism-gate PY=$(PY)
	$(MAKE) stress-gate PY=$(PY)
	$(MAKE) plasticity-gate PY=$(PY)
	$(MAKE) dependency-locks PY=$(PY)
	$(MAKE) standards-control-map PY=$(PY)
	$(MAKE) builtin-security PY=$(PY)
	$(MAKE) production-inference-security PY=$(PY)
	$(MAKE) release-mutation-delta PY=$(PY)
	$(MAKE) backend-report PY=$(PY)
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/publish_release_evidence.py
	$(MAKE) local-production-preflight PY=$(PY)

backend-report:
	rm -rf reports/regression/shards
	mkdir -p reports/regression/shards
	for index in $$(seq 0 $$(( $(REGRESSION_SHARDS) - 1 ))); do \
	  $(MAKE) regression-shard SHARD_INDEX=$$index PY=$(PY) || exit 1; \
	done
	$(MAKE) regression-shard-merge PY=$(PY)
	PYTHONPATH=apps/api/src:scripts $(PY) scripts/publish_backend_report.py
