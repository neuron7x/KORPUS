from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_public_worker_control_does_not_leak_into_strict_api_environment() -> None:
    script = (ROOT / "scripts/serve_public.sh").read_text(encoding="utf-8")

    consume = script.index('WORKERS="${KORPUS_PUBLIC_WORKERS:-8}"')
    remove = script.index("unset KORPUS_PUBLIC_WORKERS")
    launch = script.index('nohup "$PY" -m uvicorn')

    assert consume < remove < launch
