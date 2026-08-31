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

    consume = script.index('WORKERS="${KORPUS_PUBLIC_WORKERS:-2}"')
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


def test_public_api_is_loopback_only_and_resource_bounded() -> None:
    script = (ROOT / "scripts/serve_public.sh").read_text(encoding="utf-8")
    config = (ROOT / "deploy/public/nginx.conf").read_text(encoding="utf-8")

    assert "export KORPUS_BIND_HOST=127.0.0.1" in script
    assert 'export KORPUS_TRUSTED_HOSTS="localhost,127.0.0.1"' in script
    assert 'KORPUS_TRUSTED_HOSTS="*"' not in script
    assert "KORPUS_MAX_CONCURRENT_ANSWERS:-4}" in script
    assert "KORPUS_PUBLIC_WORKERS:-2}" in script
    assert "--host 127.0.0.1" in script
    assert "proxy_set_header Host 127.0.0.1;" in config


def test_the_public_deploy_does_not_invent_the_key_that_signs_the_evidence() -> None:
    """Ключ журналу доказу не сміє походити з дерева, яке кожен може клонувати.

    Тут стояв `${KORPUS_AUDIT_HMAC_KEY:-local-audit-key}` — другий вписаний літерал
    поруч із `replace-local-audit-key` із `config.py`. Заборона на плейсхолдери ловить
    лише перший. Виміряно 31.08.2026 на живій базі: 7223 події, 4061 під
    `legacy-unversioned`, і ключ живого процесу побайтово дорівнював рядку з цього
    файла — тобто засвідчених подій було НУЛЬ.

    Тест тримає причину, а не наслідок: не «немає цього рядка», а «ключ береться з
    файла поза деревом, і вписаного дефолта немає взагалі».
    """
    source = (Path(__file__).resolve().parents[3] / "scripts/serve_public.sh").read_text(
        encoding="utf-8"
    )
    executable = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert "KORPUS_AUDIT_HMAC_KEY_FILE" in executable, "ключ аудиту більше не читається з файла"
    assert "export KORPUS_AUDIT_HMAC_KEY=" not in executable, (
        "ключ аудиту знову передається значенням, а не файлом"
    )
    assert "SECRET_DIR/audit-key.txt" in executable, "ключ аудиту вийшов за межі стану поза деревом"
    # Fail-closed: скрипт мусить ВІДМОВИТИ, а не тихо відкотитись на щось відоме.
    assert "exit 69" in executable and "audit-key.txt" in executable


def test_the_api_environment_has_exactly_one_source() -> None:
    """Юніт не сміє тримати власну копію оточення API.

    Виміряно 31.08.2026: юніт ніс п'ятнадцять рядків `Environment=`, а `serve_public.sh`
    експортував свій набір. Сторож відновлює API через `systemctl --user restart`, тобто
    НЕНАГЛЯДОВИЙ шлях ішов юнітом — і після відновлення о 21:34 у живому процесі не було
    ні `KORPUS_MODEL_EGRESS_POSTURE`, ні ключа аудиту: посада лишилась `external_allowed`,
    а журнал підписувався плейсхолдером із `config.py`.

    Тест тримає причину: одна властивість — одне джерело. Не «є ці дві змінні», а
    «другого списку не існує».
    """
    unit = (ROOT / "deploy/public/korpus-public-api.service").read_text(encoding="utf-8")
    duplicated = [line for line in unit.splitlines() if line.startswith("Environment=KORPUS_")]
    assert not duplicated, f"юніт знову тримає власну копію оточення: {duplicated}"
    assert "EnvironmentFile=" in unit, "юніт не читає спільного файла оточення"
    # Fail-closed: `-` перед шляхом дозволив би старт із вгаданим оточенням.
    assert "EnvironmentFile=-" not in unit, "відсутній файл оточення став би необов'язковим"

    script = (ROOT / "scripts/serve_public.sh").read_text(encoding="utf-8")
    assert "api.env" in script, "скрипт більше не пише файла оточення"
    # Проєкція, а не третій список: імена беруться з оточення процесу.
    assert "compgen -v" in script, "файл оточення знову складається вписаним переліком"
