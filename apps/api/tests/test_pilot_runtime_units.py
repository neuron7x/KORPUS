from __future__ import annotations

import importlib.machinery
import importlib.util
import shlex
from pathlib import Path

import pytest

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


def test_pilot_api_finds_source_without_external_pythonpath() -> None:
    unit = INSTALLER.render("korpus-pilot-api.service")
    directives = dict(
        line.split("=", 1)
        for line in unit.splitlines()
        if line.startswith(("WorkingDirectory=", "ExecStart="))
    )
    command = shlex.split(directives["ExecStart"])
    app_dir = command[command.index("--app-dir") + 1]
    assert app_dir == "apps/api/src"
    source = Path(directives["WorkingDirectory"]) / app_dir
    # An explicit search path avoids pytest's configured PYTHONPATH. Finding
    # the spec does not import the application or start any server.
    spec = importlib.machinery.PathFinder.find_spec("korpus", [str(source)])
    assert spec is not None
    assert spec.origin == str(ROOT / "apps/api/src/korpus/__init__.py")


def test_pilot_web_is_loopback_proxy_to_declared_api() -> None:
    unit = INSTALLER.render("korpus-pilot-web.service")
    assert "KORPUS_API_ORIGIN=http://127.0.0.1:8040" in unit
    assert "KORPUS_WEB_PORT=8041" in unit
    assert "Requires=korpus-pilot-api.service" in unit
    assert "apps/web/dist" in unit


# These tests only render text; they never install units or contact systemd.


@pytest.mark.parametrize(
    ("root", "directory", "executable"),
    [
        ("/srv/pilot workspace", "/srv/pilot workspace", "/srv/pilot workspace"),
        ("/srv/%h/pilot%", "/srv/%%h/pilot%%", "/srv/%%h/pilot%%"),
        ("/srv/пілот", "/srv/пілот", "/srv/пілот"),
        (
            "/srv/@KORPUS_ROOT@",
            "/srv/@KORPUS_ROOT@",
            "/srv/@KORPUS_ROOT@",
        ),
    ],
)
def test_root_is_escaped_for_each_systemd_context(
    monkeypatch: pytest.MonkeyPatch, root: str, directory: str, executable: str
) -> None:
    monkeypatch.setattr(INSTALLER, "ROOT", Path(root))
    for name in INSTALLER.UNITS:
        unit = INSTALLER.render(name)
        assert f"WorkingDirectory={directory}" in unit.splitlines()
        if name == "korpus-pilot-api.service":
            assert f'ExecStart="{executable}/apps/api/.venv/bin/python" -m uvicorn ' in unit
            # Escape only substituted paths, not intentional template specifiers.
            assert "EnvironmentFile=%h/.local/state/korpus-pilot/api.env" in unit
            assert "CPUQuota=250%" in unit
        assert unit == INSTALLER.render(name)


@pytest.mark.parametrize(
    "root",
    [
        "relative/path",
        "/srv/pilot\nextra",
        "/srv/pilot\rextra",
        "/srv/pilot\textra",
        "/srv/pilot\0extra",
        "/srv/pilot\x7fextra",
        "/srv/pilot ",
        "/srv/pilot\\",
        "/srv/${HOME}",
        '/srv/pilot "quoted"',
        "/srv/pilot 'quoted'",
        r"/srv/pilot\tree",
    ],
)
def test_unrepresentable_paths_fail_before_rendering(
    monkeypatch: pytest.MonkeyPatch, root: str
) -> None:
    monkeypatch.setattr(INSTALLER, "ROOT", Path(root))
    for name in INSTALLER.UNITS:
        with pytest.raises(ValueError, match="Workspace path"):
            INSTALLER.render(name)


def test_render_rejects_unknown_units() -> None:
    with pytest.raises(ValueError, match="Unknown pilot unit"):
        INSTALLER.render("../other.service")


def test_invalid_root_does_not_write_or_contact_systemd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "not-created"
    monkeypatch.setattr(INSTALLER, "ROOT", Path('/srv/invalid"root'))
    monkeypatch.setattr(INSTALLER, "TARGET", target)

    def unexpected_subprocess(*args: object, **kwargs: object) -> None:
        pytest.fail("Invalid root must not contact systemd")

    monkeypatch.setattr(INSTALLER.subprocess, "run", unexpected_subprocess)
    with pytest.raises(ValueError, match="Workspace path"):
        INSTALLER.main()
    assert not target.exists()
