SHELL := /bin/bash
PY := apps/api/.venv/bin/python
PIP := apps/api/.venv/bin/pip

.PHONY: corpus-release corpus-release-verify security-scan reproducible-build chaos-matrix ingestion-drill load-probe backup-sqlite restore-sqlite drive-snapshot drive-public serve-public public-tunnel draft-manifest import-corpus review-token audit-export web-contract web-contract-check environment-drift environment-observe requirements-register module-budget retention-plan postgres-suite quality-gate handoff-verify openapi audit-closure desired-state supply-chain-inventory kubernetes-validate infra-validate backup-postgres restore-postgres api-install api-run api-test api-lint web-install web-run web-build bootstrap eval mutation migration-gate scale operational-gate assurance assemble-assurance snapshot audit-verify validate check release infra-secrets infra-up infra-support infra-down package clean

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
	PYTHONPATH=apps/api/src $(PY) -m pytest apps/api/tests --cov=apps/api/src/korpus --cov-branch --cov-report=term-missing --cov-report=json:var/coverage.json --cov-fail-under=82
	PYTHONPATH=apps/api/src $(PY) scripts/check_coverage_thresholds.py

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

# The browser's copy of the request constraints and the role table, generated from
# contracts/openapi.json and policy.py. Hand-editing apps/web/public/contract.js creates
# a second copy of the domain rules; the copy is the one that drifts.
web-contract:
	PYTHONPATH=apps/api/src $(PY) scripts/generate_web_contract.py

web-contract-check:
	PYTHONPATH=apps/api/src $(PY) scripts/generate_web_contract.py --check

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

module-budget:
	PYTHONPATH=apps/api/src $(PY) scripts/check_module_budget.py

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
	PYTHONPATH=apps/api/src $(PY) scripts/build_audit_closure.py

desired-state:
	python3 scripts/generate_desired_state.py --check

# $(PY), not python3: this reads license metadata from the installed distributions, so
# a bare interpreter resolves whichever packages happen to be on the system — five of
# sixty-eight, when this was written. The lock is the environment it must be asked in.
supply-chain-inventory:
	PYTHONPATH=apps/api/src $(PY) scripts/generate_supply_chain_inventory.py

kubernetes-validate:
	python3 scripts/validate_kubernetes.py

# audit-closure is deliberately NOT here: it resolves citations that include
# var/mutation-report.json, which `mutation` produces. As a prerequisite of `validate`
# it ran first and passed only on a tree where an earlier run had left the file behind.
validate: handoff-verify openapi desired-state supply-chain-inventory module-budget requirements-register
	python3 scripts/validate_repository.py
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
	docker compose up -d --wait web

infra-support: infra-secrets
	docker compose up -d --wait postgres minio otel-collector migrate minio-init

infra-down:
	docker compose down

package:
	bash scripts/package_repository.sh

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml var dist apps/web/dist apps/web/.next
