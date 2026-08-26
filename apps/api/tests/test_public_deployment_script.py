from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_public_worker_control_does_not_leak_into_strict_api_environment() -> None:
    script = (ROOT / "scripts/serve_public.sh").read_text(encoding="utf-8")

    consume = script.index('WORKERS="${KORPUS_PUBLIC_WORKERS:-8}"')
    remove = script.index("unset KORPUS_PUBLIC_WORKERS")
    launch = script.index('nohup "$PY" -m uvicorn')

    assert consume < remove < launch


def test_public_deployment_defaults_to_the_admitted_full_runtime() -> None:
    script = (ROOT / "scripts/serve_public.sh").read_text(encoding="utf-8")

    assert 'RUNTIME_RELEASE="${KORPUS_RUNTIME_RELEASE:-corpus-v6-20260807}"' in script
    assert 'sqlite:///$RUNTIME_ROOT/korpus.db' in script
    assert '$RUNTIME_ROOT/objects' in script
    assert 'scripts/audit_runtime_corpus.py' in script
    assert 'runtime corpus admission failed' in script
