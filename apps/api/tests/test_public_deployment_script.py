import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _argv(source: str, *head: str) -> list[str] | None:
    """The literal argument list of a subprocess call, read from the AST, not the text.

    The call is `run([...])` with string literals, so the list is recoverable exactly;
    reading it structurally makes these assertions independent of line wrapping.
    """
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.List):
            continue
        values = [
            element.value
            for element in node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
        if values[: len(head)] == list(head):
            return values
    return None


def test_public_worker_control_does_not_leak_into_strict_api_environment() -> None:
    script = (ROOT / "scripts/serve_public.sh").read_text(encoding="utf-8")

    consume = script.index('WORKERS="${KORPUS_PUBLIC_WORKERS:-8}"')
    remove = script.index("unset KORPUS_PUBLIC_WORKERS")
    launch = script.index('nohup "$PY" -m uvicorn')

    assert consume < remove < launch


def test_public_deployment_defaults_to_the_admitted_full_runtime() -> None:
    script = (ROOT / "scripts/serve_public.sh").read_text(encoding="utf-8")

    assert 'RUNTIME_RELEASE="${KORPUS_RUNTIME_RELEASE:-corpus-v6-20260807}"' in script
    assert "sqlite:///$RUNTIME_ROOT/korpus.db" in script
    assert "$RUNTIME_ROOT/objects" in script
    assert "scripts/audit_runtime_corpus.py" in script
    assert "runtime corpus admission failed" in script


def test_public_edge_returns_typed_rate_limit_refusals() -> None:
    config = (ROOT / "deploy/public/nginx.conf").read_text(encoding="utf-8")

    assert "error_page 429 = @rate_limited;" in config
    assert '"reason":"edge_rate_limited"' in config
    assert "add_header Retry-After 2 always;" in config
    assert "default_type application/json;" in config


def test_public_edge_survives_daemon_and_host_restarts() -> None:
    """Both deployment paths pass --restart unless-stopped to `docker run`.

    Asserted on the argument list rather than one exact line: `ruff format` wraps a long
    argv across lines, and a formatting pass then reads as the restart policy going missing.
    """
    script = (ROOT / "scripts/serve_public.sh").read_text(encoding="utf-8")
    deployer = (ROOT / "scripts/deploy_public_web.py").read_text(encoding="utf-8")

    assert "--restart unless-stopped" in script
    argv = _argv(deployer, "docker", "run")
    assert argv is not None, "deploy_public_web.py no longer runs a container at all"
    assert "--restart" in argv, "the edge container is started without a restart policy"
    assert argv[argv.index("--restart") + 1] == "unless-stopped"


def test_public_edge_runs_the_hardened_image_in_both_deployment_paths() -> None:
    script = (ROOT / "scripts/serve_public.sh").read_text(encoding="utf-8")
    deployer = (ROOT / "scripts/deploy_public_web.py").read_text(encoding="utf-8")
    dockerfile = (ROOT / "deploy/public/Dockerfile.edge").read_text(encoding="utf-8")

    image = "korpus-public-edge-runtime:nginx-1.31.3-alpine-r1"
    assert image in script and image in deployer
    assert "docker build --quiet --file deploy/public/Dockerfile.edge" in script
    assert _argv(deployer, "docker", "build") is not None
    assert "RUN apk upgrade --no-cache" in dockerfile
    assert "USER nginx:nginx" in dockerfile
