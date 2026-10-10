from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "install_pilot_runtime", ROOT / "scripts/install_pilot_runtime.py"
)
assert SPEC and SPEC.loader
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


def test_pilot_api_has_unambiguous_non_conflicting_port() -> None:
    unit = INSTALLER.render("korpus-pilot-api.service")
    assert "--port 8040" in unit
    assert "--port 8030" not in unit
    assert str(ROOT) in unit


def test_pilot_web_is_loopback_proxy_to_declared_api() -> None:
    unit = INSTALLER.render("korpus-pilot-web.service")
    assert "KORPUS_API_ORIGIN=http://127.0.0.1:8040" in unit
    assert "KORPUS_WEB_PORT=8041" in unit
    assert "Requires=korpus-pilot-api.service" in unit
    assert "apps/web/dist" in unit
