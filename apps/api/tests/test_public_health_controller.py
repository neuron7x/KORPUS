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
    # Витримка добігла — відновлення дозволене знову. Дія вже ІНША: див.
    # test_second_attempt_at_one_outage_is_a_different_action. Тут перевіряється
    # витримка, а не те, яка саме сходинка.
    state, actions = health.transition(state, {"api": True, "edge": True, "public": False}, 1_361)
    assert actions == ["recycle_funnel"]


def test_success_resets_only_the_recovered_component_counter() -> None:
    state = health.initial_state()
    state["failures"] = {"api": 3, "edge": 4, "public": 5}
    state, actions = health.transition(state, {"api": True, "edge": False, "public": False}, 2_000)
    assert actions == ["refresh_edge"]
    assert state["failures"] == {"api": 0, "edge": 5, "public": 6}


def test_edge_recovery_rotates_the_expiring_identity_not_only_the_container() -> None:
    assert health.ACTION_COMMANDS["refresh_edge"] == (
        ["env", "KORPUS_PUBLIC_EDGE_ONLY=true", "bash", "scripts/serve_public.sh"],
    )


def test_second_attempt_at_one_outage_is_a_different_action() -> None:
    """Повторення ідемпотентної команди не є ескалацією.

    31.08.2026 сторож двічі виконав `restore_funnel` над мертвим URL і двічі дістав
    успіх: команда вмикає вже ввімкнене. Друга сходинка мусить бути ІНШОЮ дією.
    """
    state = health.initial_state()
    down = {"api": True, "edge": True, "public": False}
    for now in (1_000, 1_060):
        state, first = health.transition(state, down, now)
    assert first == ["restore_funnel"]
    state, second = health.transition(state, down, 1_400)
    assert second == ["recycle_funnel"]
    assert second != first


def test_ladder_does_not_climb_past_its_last_rung() -> None:
    state = health.initial_state()
    down = {"api": True, "edge": True, "public": False}
    seen = []
    for now in (1_000, 1_060, 1_400, 1_800, 2_200):
        state, actions = health.transition(state, down, now)
        seen.extend(actions)
    assert seen == ["restore_funnel", "recycle_funnel", "recycle_funnel", "recycle_funnel"]


def test_health_resets_the_rung_so_a_new_outage_starts_gently() -> None:
    """Наступний збій — новий збій; починати його з найбільшого втручання нема підстав."""
    state = health.initial_state()
    down = {"api": True, "edge": True, "public": False}
    for now in (1_000, 1_060, 1_400):
        state, _ = health.transition(state, down, now)
    state, _ = health.transition(state, {"api": True, "edge": True, "public": True}, 1_500)
    assert state["attempts"]["public"] == 0
    for now in (2_000, 2_060):
        state, actions = health.transition(state, down, now)
    assert actions == ["restore_funnel"]


def test_components_without_a_second_rung_never_invent_one() -> None:
    """Вигадана ескалація гірша за її відсутність: вона діє, не знаючи, чи є ефект."""
    state = health.initial_state()
    down = {"api": False, "edge": False, "public": False}
    seen = []
    for now in (1_000, 1_060, 1_400, 1_800):
        state, actions = health.transition(state, down, now)
        seen.extend(actions)
    assert set(seen) == {"restart_api"}


def test_execute_runs_the_whole_sequence_not_only_its_first_command(monkeypatch) -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    monkeypatch.setattr(
        health.subprocess, "run", lambda command, **_: calls.append(command) or Result()
    )
    assert health.execute("recycle_funnel") is True
    assert calls == [
        ["tailscale", "funnel", "--bg", "off"],
        ["tailscale", "funnel", "--bg", "8081"],
    ]


def test_installed_service_is_bound_to_canonical_root() -> None:
    rendered = installer.render("korpus-public-watchdog.service")
    assert "@KORPUS_ROOT@" not in rendered
    assert f"WorkingDirectory={installer.ROOT}" in rendered
