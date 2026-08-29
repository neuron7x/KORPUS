"""The reconciler's wait branch is covered on purpose, not by a slow test run.

`reconcile_loop` in main.py waits on `stop_reconciler` with the configured interval and
`continue`s when that wait times out. Nothing exercised that branch directly: it was covered
only when some unrelated test happened to hold a client open longer than the 2-second
default. A 293-second suite covered it; a 229-second suite did not, and coverage moved
97% -> 96% with no code change. A branch whose coverage depends on how long the suite takes
is a branch nobody tests.

This drives the loop through at least two iterations by shortening the interval to the
configured floor and waiting for the second reconcile call, so the timeout path is taken
deterministically and the suite's duration stops being an input.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from korpus.config import Settings
from korpus.infrastructure.repository import SqlRepository
from korpus.main import create_app


@pytest.fixture
def short_interval_settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        schema_mode="auto",
        database_url=f"sqlite:///{tmp_path / 'reconciler.db'}",
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "audit-anchor.json",
        audit_hmac_key="test-audit-key",
        auth_mode="dev",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
        # The configured floor (config.py: ge=0.2). Two iterations cost 0.2s, not 2s.
        audit_reconcile_interval_seconds=0.2,
    )


def test_the_reconciler_loops_again_after_its_wait_times_out(
    short_interval_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    original = SqlRepository.reconcile_audit_anchor

    def counted(self: SqlRepository, *, limit: int | None = None) -> int:
        calls.append(len(calls))
        return original(self, limit=limit)

    monkeypatch.setattr(SqlRepository, "reconcile_audit_anchor", counted)

    with TestClient(create_app(short_interval_settings)):
        deadline = time.monotonic() + 5.0
        while len(calls) < 3 and time.monotonic() < deadline:
            time.sleep(0.02)

    # 1 = repository.initialize during start-up, 2 = the loop's first pass, 3 = it waited,
    # timed out and continued. Asserting on 2 would survive `continue` becoming `break`.
    assert len(calls) >= 3, f"reconciler ran {len(calls)} time(s); the wait branch never fired"


def test_a_reconcile_failure_does_not_stop_the_loop(
    short_interval_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The except path and the wait path are separate branches; both must survive.

    `repository.initialize` reconciles once during start-up (main.py:66, outside the loop's
    try), and a failure there is a fail-fast the application should not survive. So only the
    calls after start-up fail here — otherwise this test would assert on start-up behaviour
    while claiming to test the loop.
    """
    calls: list[int] = []
    original = SqlRepository.reconcile_audit_anchor

    def failing_after_startup(self: SqlRepository, *, limit: int | None = None) -> int:
        calls.append(len(calls))
        if len(calls) == 1:
            return original(self, limit=limit)
        raise RuntimeError("anchor store unavailable")

    monkeypatch.setattr(SqlRepository, "reconcile_audit_anchor", failing_after_startup)

    with TestClient(create_app(short_interval_settings)):
        deadline = time.monotonic() + 5.0
        while len(calls) < 3 and time.monotonic() < deadline:
            time.sleep(0.02)

    # 1 = start-up, 2 = the loop's first pass (which raises), 3 = it looped anyway.
    assert len(calls) >= 3, f"a failing reconcile stopped the loop after {len(calls)} call(s)"
