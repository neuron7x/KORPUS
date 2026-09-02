from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INSTALL_SCRIPT = ROOT / "scripts/install_public_runtime.py"
SPEC = importlib.util.spec_from_file_location("install_public_runtime", INSTALL_SCRIPT)
assert SPEC is not None and SPEC.loader is not None
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


def test_api_unit_is_loopback_only_and_bounded() -> None:
    unit = INSTALLER.render("korpus-public-api.service")

    assert "@KORPUS_ROOT@" not in unit
    assert f"WorkingDirectory={ROOT}" in unit
    assert "KORPUS_BIND_HOST=127.0.0.1" in unit
    assert "KORPUS_TRUSTED_HOSTS=localhost,127.0.0.1" in unit
    assert "--host 127.0.0.1" in unit
    assert "KORPUS_MAX_CONCURRENT_ANSWERS=4" in unit
    assert "CPUQuota=250%" in unit
    assert "MemoryHigh=2G" in unit
    assert "MemoryMax=3G" in unit
    assert "Restart=on-failure" in unit
    assert (
        f'ExecCondition="{ROOT}/apps/api/.venv/bin/python" '
        f'"{ROOT}/scripts/audit_runtime_corpus.py" '
        f'--database "{ROOT}/var/runtime/corpus-v6-20260807/korpus.db" '
        f'--object-root "{ROOT}/var/runtime/corpus-v6-20260807/objects" '
        f'--out "{ROOT}/var/public/runtime-corpus-audit-api.json"'
    ) in unit


def test_worker_unit_supervises_and_bounds_the_ingestion_loop() -> None:
    unit = INSTALLER.render("korpus-worker.service")

    assert "@KORPUS_ROOT@" not in unit
    assert "KORPUS_RUNTIME_ROLE=worker" in unit
    assert "-m korpus.cli worker-loop --idle-seconds 1" in unit
    assert "CPUQuota=250%" in unit
    assert "MemoryHigh=3G" in unit
    assert "MemoryMax=5G" in unit
    assert "Restart=on-failure" in unit
    assert "Nice=5" in unit
    assert "IOSchedulingPriority=7" in unit
    assert (
        f'ExecCondition="{ROOT}/apps/api/.venv/bin/python" '
        f'"{ROOT}/scripts/audit_runtime_corpus.py" '
        f'--database "{ROOT}/var/runtime/corpus-v6-20260807/korpus.db" '
        f'--object-root "{ROOT}/var/runtime/corpus-v6-20260807/objects" '
        f'--out "{ROOT}/var/public/runtime-corpus-audit-worker.json"'
    ) in unit


def test_units_use_secret_file_and_do_not_allow_resource_control_overrides() -> None:
    for name in INSTALLER.UNITS:
        unit = INSTALLER.render(name)
        assert "KORPUS_JWT_SECRET=" not in unit
        assert "KORPUS_JWT_SECRET_FILE=%h/.local/state/korpus-public/jwt-secret.txt" in unit
        # Директива, не згадка. Перевірка підрядком ловила власний КОМЕНТАР юніта,
        # який пояснює, чому цієї директиви тут немає, — тобто карала за документацію
        # рішення. Намір той самий: юніт оголошує оточення сам, і жодного зовнішнього
        # файла не читає; тепер він виражений над рядками-директивами.
        directives = [
            line.strip() for line in unit.splitlines() if not line.lstrip().startswith("#")
        ]
        assert not any(line.startswith("EnvironmentFile=") for line in directives)
