.PHONY: api-install api-run api-test api-lint web-install web-run check infra-up infra-down

api-install:
	python3 -m venv apps/api/.venv
	apps/api/.venv/bin/pip install -e 'apps/api[dev]'

api-run:
	apps/api/.venv/bin/uvicorn korpus.main:app --app-dir apps/api/src --reload

api-test:
	apps/api/.venv/bin/pytest apps/api/tests

api-lint:
	apps/api/.venv/bin/ruff check apps/api/src apps/api/tests
	apps/api/.venv/bin/mypy apps/api/src

web-install:
	pnpm --dir apps/web install

web-run:
	pnpm --dir apps/web dev

check:
	python3 scripts/validate_repository.py
	$(MAKE) api-test
	$(MAKE) api-lint
	pnpm --dir apps/web lint
	pnpm --dir apps/web typecheck

infra-up:
	docker compose up -d

infra-down:
	docker compose down

