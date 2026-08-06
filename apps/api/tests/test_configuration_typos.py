"""A misspelled KORPUS_* variable must not leave a control silently off.

`SettingsConfigDict(extra="ignore")` drops an unrecognised variable without a word.
Measured 2026-08-06: with `KORPUS_REQUIRE_SOURCE_SIGNATURE=true` set — singular, where
the field is `require_source_signatures` — `Settings()` constructs cleanly and
`require_source_signatures` is `False`. The deployment reads correct in review, the
signature requirement is not in force, and nothing anywhere says so.

`extra="forbid"` cannot be the fix: the backup, recovery and role-provisioning scripts
own `KORPUS_*` names too and share the process environment in CI and in compose. So the
namespace is checked against the union of the settings fields and a declared list of
operational names, and the declaration is the point — a rule that accepts whatever it
finds is the rule being replaced.
"""

from __future__ import annotations

import pytest
from korpus.config import OPERATIONAL_VARIABLES, Settings, unknown_settings_variables


def test_a_misspelled_setting_is_named() -> None:
    unknown = unknown_settings_variables({"KORPUS_REQUIRE_SOURCE_SIGNATURE": "true"})

    assert unknown == ["KORPUS_REQUIRE_SOURCE_SIGNATURE"]


def test_the_correctly_spelled_setting_is_accepted() -> None:
    """The dual. Without it the check is satisfied by rejecting everything."""
    assert unknown_settings_variables({"KORPUS_REQUIRE_SOURCE_SIGNATURES": "true"}) == []


def test_operational_variables_are_not_flagged() -> None:
    """The scripts share the namespace; flagging them would make the check unusable."""
    environment = dict.fromkeys(OPERATIONAL_VARIABLES, "x")

    assert unknown_settings_variables(environment) == []


def test_variables_outside_the_namespace_are_ignored() -> None:
    """PATH, HOME and every other variable in the environment are not this check's."""
    assert unknown_settings_variables({"PATH": "/usr/bin", "HOME": "/root"}) == []


def test_every_settings_field_is_reachable_by_its_prefixed_name() -> None:
    """The mapping this check assumes: field `x_y` is `KORPUS_X_Y`.

    If pydantic's env-name derivation ever stopped matching, `unknown_settings_variables`
    would start reporting real settings as typos — the loud direction, but still wrong.
    """
    for name in Settings.model_fields:
        assert unknown_settings_variables({f"KORPUS_{name.upper()}": "x"}) == []


def test_the_app_refuses_to_start_on_an_unrecognised_variable(monkeypatch) -> None:
    """Refused, not warned. A control an operator believes is on and is not is worse
    than a process that does not start."""
    from korpus.main import create_app

    monkeypatch.setenv("KORPUS_REQUIRE_SOURCE_SIGNATURE", "true")

    with pytest.raises(ValueError, match="unrecognised KORPUS_"):
        create_app(Settings(environment="test", auth_mode="disabled"))


def test_the_app_starts_when_every_variable_is_recognised(monkeypatch) -> None:
    monkeypatch.setenv("KORPUS_REQUIRE_SOURCE_SIGNATURES", "false")

    assert create_app_ok(Settings(environment="test", auth_mode="disabled"))


def create_app_ok(settings: Settings) -> bool:
    from korpus.main import create_app

    return create_app(settings) is not None
