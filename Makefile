SHELL := /bin/bash
PY := apps/api/.venv/bin/python
PIP := apps/api/.venv/bin/pip

.PHONY: web-contract web-contract-check environment-drift environment-observe requirements-register module-budget retention-plan postgres-suite quality-gate handoff-verify openapi audit-closure desired-state supply-chain-inventory kubernetes-validate infra-validate backup-postgres restore-postgres api-install api-run api-test api-lint web-install web-run web-build bootstrap eval mutation migration-gate scale operational-gate assurance assemble-assurance snapshot audit-verify validate check release infra-secrets infra-up infra-support infra-down package clean

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
