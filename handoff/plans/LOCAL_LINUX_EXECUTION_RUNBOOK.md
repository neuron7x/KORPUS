# Local Linux execution runbook

## Preferred path: clone full history from bundle

```bash
unzip KORPUS_LOCAL_DEVELOPMENT_HANDOFF_v5.1.0.zip
cd KORPUS_LOCAL_DEVELOPMENT_HANDOFF_v5.1.0
git clone git/KORPUS_LOCAL_DEVELOPMENT_HANDOFF_v5.1.0.bundle korpus
cd korpus
git switch main
```

## Python-only baseline

```bash
python3 --version
make api-install
make bootstrap
make api-test
python3 scripts/verify_handoff_contract.py
```

## Web baseline

```bash
make web-install
make web-build
```

## Integrated local infrastructure

```bash
cp .env.example .env
make infra-secrets
make infra-up
```

Only use synthetic/open fixtures until corpus rights, classification and authorization are closed.

## Agent worktree

```bash
scripts/create_agent_worktree.sh claude issue-001-live-postgres
# or
scripts/create_agent_worktree.sh codex issue-002-supply-chain
```

Never run Claude Code and Codex in one worktree or against one mutable test database.

## Before merge

```bash
make validate
make api-test
make eval
make mutation
make migration-gate
make scale
make operational-gate
make web-build
python3 scripts/verify_handoff_contract.py
```

Run `make check` only when Ruff, mypy, Node and required services are available. Report skipped gates explicitly.
