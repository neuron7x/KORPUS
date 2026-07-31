SHELL := /bin/bash
PY := apps/api/.venv/bin/python
PIP := apps/api/.venv/bin/pip

.PHONY: api-install api-run api-test api-lint web-install web-run web-build bootstrap eval audit-verify validate check infra-secrets infra-up infra-support infra-down package clean

api-install:
	python3 -m venv apps/api/.venv
	$(PIP) install -e 'apps/api[dev]'

api-run:
	mkdir -p var/objects
	$(PY) -m uvicorn korpus.main:app --app-dir apps/api/src --host 127.0.0.1 --port 8000 --reload

api-test:
	$(PY) -m pytest apps/api/tests --cov=apps/api/src/korpus --cov-report=term-missing --cov-fail-under=85

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

audit-verify:
	PYTHONPATH=apps/api/src $(PY) scripts/verify_audit.py

validate:
	python3 scripts/validate_repository.py

check: validate api-test api-lint eval

infra-secrets:
	bash scripts/init_local_secrets.sh

infra-up: infra-secrets
	docker compose up -d api web

infra-support: infra-secrets
	docker compose --profile support up -d

infra-down:
	docker compose down

package:
	bash scripts/package_repository.sh

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml var dist apps/web/.next
