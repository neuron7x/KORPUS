.PHONY: api-install api-run api-test api-cov api-lint evals mutation mutation-baseline \
        web-install web-run check gate infra-up infra-down

api-install:
	python3 -m venv apps/api/.venv
	apps/api/.venv/bin/pip install -e 'apps/api[dev]'

api-run:
	apps/api/.venv/bin/uvicorn korpus.main:app --app-dir apps/api/src --reload

api-test:
	apps/api/.venv/bin/pytest apps/api/tests

api-cov:
	apps/api/.venv/bin/pytest apps/api/tests --cov=korpus --cov-branch \
	  --cov-report=term-missing --cov-fail-under=99

api-lint:
	apps/api/.venv/bin/ruff check apps/api/src apps/api/tests
	apps/api/.venv/bin/mypy apps/api/src

# Fixtures replayed through the real pipeline. Exits non-zero on an empty dataset,
# because a run with nothing in it prints the same "0 failures" as a passing one.
evals:
	apps/api/.venv/bin/python scripts/run_evals.py

# Coverage says a line ran; this says the suite notices when the line is wrong.
mutation:
	apps/api/.venv/bin/python tools/mutation.py

mutation-baseline:
	apps/api/.venv/bin/python tools/mutation.py --update-baseline

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

# What CI runs. `check` is the fast loop; `gate` is what a merge has to survive.
gate: check evals mutation

infra-up:
	docker compose up -d

infra-down:
	docker compose down
