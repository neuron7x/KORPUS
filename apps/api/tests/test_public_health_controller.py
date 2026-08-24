from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/public_health_controller.py"
SPEC = importlib.util.spec_from_file_location("public_health_controller", SCRIPT)
assert SPEC and SPEC.loader
health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(health)


INSTALL_SCRIPT = SCRIPT.parents[1] / "scripts/install_public_watchdog.py"
INSTALL_SPEC = importlib.util.spec_from_file_location("install_public_watchdog", INSTALL_SCRIPT)
assert INSTALL_SPEC and INSTALL_SPEC.loader
installer = importlib.util.module_from_spec(INSTALL_SPEC)
INSTALL_SPEC.loader.exec_module(installer)


def test_recovery_requires_two_failures_and_obeys_dependency_order() -> None:
    state = health.initial_state()
    state, actions = health.transition(state, {"api": False, "edge": False, "public": False}, 1_000)
    assert actions == []
    state, actions = health.transition(state, {"api": False, "edge": False, "public": False}, 1_060)
    assert actions == ["restart_api"]


def test_public_recovery_requires_healthy_local_chain_and_cooldown() -> None:
    state = health.initial_state()
    for now in (1_000, 1_060):
        state, actions = health.transition(state, {"api": True, "edge": True, "public": False}, now)
    assert actions == ["restore_funnel"]
    state, actions = health.transition(state, {"api": True, "edge": True, "public": False}, 1_120)
    assert actions == []
    state, actions = health.transition(state, {"api": True, "edge": True, "public": False}, 1_361)
    assert actions == ["restore_funnel"]


def test_success_resets_only_the_recovered_component_counter() -> None:
    state = health.initial_state()
    state["failures"] = {"api": 3, "edge": 4, "public": 5}
    state, actions = health.transition(state, {"api": True, "edge": False, "public": False}, 2_000)
    assert actions == ["restart_edge"]
    assert state["failures"] == {"api": 0, "edge": 5, "public": 6}


def test_installed_service_is_bound_to_canonical_root() -> None:
    rendered = installer.render("korpus-public-watchdog.service")
    assert "@KORPUS_ROOT@" not in rendered
    assert f"WorkingDirectory={installer.ROOT}" in rendered
