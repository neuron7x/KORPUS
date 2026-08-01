SHELL := /bin/bash
PY := apps/api/.venv/bin/python
PIP := apps/api/.venv/bin/pip

.PHONY: infra-validate backup-postgres restore-postgres api-install api-run api-test api-lint web-install web-run web-build bootstrap eval mutation migration-gate scale operational-gate assurance assemble-assurance snapshot audit-verify validate check release infra-secrets infra-up infra-support infra-down package clean

api-install:
	python3 -m venv apps/api/.venv
	$(PIP) install --no-deps --requirement apps/api/requirements.dev.lock

api-run:
	mkdir -p var/objects
	$(PY) -m uvicorn korpus.main:app --app-dir apps/api/src --host 127.0.0.1 --port 8000 --reload

api-test:
	PYTHONPATH=apps/api/src $(PY) -m pytest apps/api/tests --cov=apps/api/src/korpus --cov-branch --cov-report=term-missing --cov-fail-under=82

api-lint:
	$(PY) -m ruff check apps/api/src apps/api/tests scripts
	$(PY) -m mypy apps/api/src

web-install:
	npm --prefix apps/web ci

web-run:
	npm --prefix apps/web run dev

web-build:
	npm --prefix apps/web run lint
	npm --prefix apps/web run typecheck
	npm --prefix apps/web run build

bootstrap:
	mkdir -p var/objects
	PYTHONPATH=apps/api/src $(PY) scripts/bootstrap_local.py

eval:
	PYTHONPATH=apps/api/src $(PY) scripts/run_evals.py

mutation:
	PYTHONPATH=apps/api/src $(PY) scripts/run_mutation_tests.py

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

audit-verify:
	PYTHONPATH=apps/api/src $(PY) scripts/verify_audit.py

validate:
	python3 scripts/validate_repository.py
	python3 scripts/validate_infrastructure.py

infra-validate:
	python3 scripts/validate_infrastructure.py

backup-postgres:
	scripts/backup_postgres.sh

restore-postgres:
	scripts/restore_postgres.sh "$(BACKUP)"

check: validate api-test api-lint eval mutation migration-gate scale operational-gate web-build

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
