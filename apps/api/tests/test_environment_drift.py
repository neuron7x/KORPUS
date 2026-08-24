"""OPS-004: the environment either matches what was approved, or it is named where not.

The tests that matter here are the negative controls. A drift checker that reports
IN_SYNC is doing its job only if it is also capable of reporting the four ways it can
fail — and the one that gets lost is UNOBSERVED, because a checker that treats "nothing
reported" as "nothing wrong" passes every test written from the happy path.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from korpus.application import environment_drift as drift

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/check_environment_drift.py"
MANIFEST = ROOT / "config/operations/desired-state.json"

APPROVED = {"a.yml": "a" * 64, "b.yml": "b" * 64}


def test_matching_digests_are_in_sync() -> None:
    report = drift.compare(APPROVED, dict(APPROVED))
    assert report.in_sync
    assert report.status == drift.IN_SYNC
    assert report.checked == 2
    assert drift.blocked(report)[0] is False


def test_changed_digest_is_drift_and_carries_both_sides() -> None:
    report = drift.compare(APPROVED, {"a.yml": "a" * 64, "b.yml": "c" * 64})
    findings = report.of_state(drift.DRIFTED)
    assert [finding.path for finding in findings] == ["b.yml"]
    # Both digests travel, because "b.yml drifted" without them tells an operator
    # nothing they can act on.
    assert findings[0].approved_sha256 == "b" * 64
    assert findings[0].observed_sha256 == "c" * 64
    assert drift.blocked(report)[0] is True


def test_absent_from_observation_is_unobserved_not_in_sync() -> None:
    """The finding this whole module exists for.

    A reconciler handed a partial observation must not answer for the artefacts it was
    not told about. Deleting a file from the cluster produces exactly this input.
    """
    report = drift.compare(APPROVED, {"a.yml": "a" * 64})
    assert not report.in_sync
    assert [finding.path for finding in report.of_state(drift.UNOBSERVED)] == ["b.yml"]
    assert report.status == drift.DRIFTED


def test_present_but_unreadable_is_unobserved_not_drift() -> None:
    report = drift.compare(APPROVED, {"a.yml": "a" * 64, "b.yml": None})
    assert [finding.path for finding in report.of_state(drift.UNOBSERVED)] == ["b.yml"]
    assert report.of_state(drift.DRIFTED) == ()


def test_undeclared_artefact_is_extra_not_drift() -> None:
    report = drift.compare(APPROVED, {**APPROVED, "rogue.yml": "d" * 64})
    extra = report.of_state(drift.EXTRA)
    assert [finding.path for finding in extra] == ["rogue.yml"]
    assert extra[0].approved_sha256 is None
    # Not folded into DRIFTED: nothing approved it, so there is no approved digest to
    # have drifted from.
    assert report.of_state(drift.DRIFTED) == ()


def test_empty_desired_state_with_running_artefacts_is_not_in_sync() -> None:
    """Nothing declared plus something running is the worst case, not the clean one."""
    report = drift.compare({}, {"rogue.yml": "d" * 64})
    assert not report.in_sync
    assert report.checked == 0


def test_blocked_reason_counts_every_state() -> None:
    report = drift.compare(
        {"a.yml": "a" * 64, "b.yml": "b" * 64, "c.yml": "c" * 64},
        {"a.yml": "z" * 64, "b.yml": None, "rogue.yml": "d" * 64},
    )
    is_blocked, reason = drift.blocked(report)
    assert is_blocked
    assert "1 artefacts differ" in reason
    assert "2 were not observed" in reason  # b.yml unreadable, c.yml absent
    assert "1 are running undeclared" in reason


def test_findings_are_ordered_so_two_runs_compare() -> None:
    report = drift.compare(
        {"z.yml": "1" * 64, "a.yml": "2" * 64}, {"z.yml": "9" * 64, "a.yml": "8" * 64}
    )
    assert [finding.path for finding in report.findings] == ["a.yml", "z.yml"]


def test_report_serialises_with_counts_per_state() -> None:
    report = drift.compare(APPROVED, {"a.yml": "z" * 64})
    payload = report.as_dict()
    assert payload["counts"] == {drift.DRIFTED: 1, drift.UNOBSERVED: 1}
    assert payload["artefacts_declared"] == 2
    assert json.dumps(payload)


def test_desired_state_is_read_from_the_manifest_not_the_working_tree() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    desired = drift.desired_from_manifest(manifest)
    assert desired
    assert all(len(sha) == 64 for sha in desired.values())
    assert ".gitlab-ci.yml" in desired


def test_manifest_without_records_refuses_rather_than_returning_empty() -> None:
    """An empty desired state would make every environment IN_SYNC."""
    with pytest.raises(ValueError):
        drift.desired_from_manifest({"schema": "korpus.desired-state.v1"})


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False
    )


def test_script_observes_the_working_tree_and_matches_the_manifest(tmp_path: Path) -> None:
    """The committed tree is the one the manifest describes, so observing it is clean."""
    observation = tmp_path / "observed.json"
    taken = _run("--observe", str(ROOT), "--out", str(observation))
    assert taken.returncode == 0, taken.stderr
    checked = _run("--observation", str(observation))
    assert checked.returncode == 0, checked.stdout
    assert json.loads(checked.stdout)["status"] == drift.IN_SYNC


def test_script_exits_nonzero_when_a_declared_artefact_changed(tmp_path: Path) -> None:
    observation = tmp_path / "observed.json"
    assert _run("--observe", str(ROOT), "--out", str(observation)).returncode == 0
    payload = json.loads(observation.read_text(encoding="utf-8"))
    payload["observed"][".gitlab-ci.yml"] = hashlib.sha256(b"tampered").hexdigest()
    observation.write_text(json.dumps(payload), encoding="utf-8")

    checked = _run("--observation", str(observation))
    assert checked.returncode == 1
    report = json.loads(checked.stdout)
    assert report["blocked"] is True
    assert [f["path"] for f in report["findings"]] == [".gitlab-ci.yml"]


def test_script_reports_a_deleted_artefact_as_unobserved(tmp_path: Path) -> None:
    observation = tmp_path / "observed.json"
    assert _run("--observe", str(ROOT), "--out", str(observation)).returncode == 0
    payload = json.loads(observation.read_text(encoding="utf-8"))
    payload["observed"].pop(".gitlab-ci.yml")
    observation.write_text(json.dumps(payload), encoding="utf-8")

    checked = _run("--observation", str(observation))
    assert checked.returncode == 1
    states = {f["path"]: f["state"] for f in json.loads(checked.stdout)["findings"]}
    assert states[".gitlab-ci.yml"] == drift.UNOBSERVED


def test_observing_an_empty_tree_reports_every_artefact_missing(tmp_path: Path) -> None:
    """--observe on a wrong root must not silently produce a small clean observation."""
    observation = tmp_path / "observed.json"
    empty = tmp_path / "nothing"
    empty.mkdir()
    assert _run("--observe", str(empty), "--out", str(observation)).returncode == 0
    payload = json.loads(observation.read_text(encoding="utf-8"))
    assert payload["observed"]
    assert all(value is None for value in payload["observed"].values())

    checked = _run("--observation", str(observation))
    assert checked.returncode == 1
    report = json.loads(checked.stdout)
    assert report["counts"][drift.UNOBSERVED] == report["artefacts_declared"]


def test_script_refuses_to_answer_without_an_observation() -> None:
    """No cluster read means no verdict — not a default of IN_SYNC."""
    result = _run()
    assert result.returncode == 2
    assert "does not read a cluster" in json.loads(result.stdout)["reason"]


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def test_an_observation_without_a_timestamp_is_refused() -> None:
    """The replay this closes: an observation taken before the change, compared after.

    It produces a verdict identical to a current one. "Periodic attestation" is in the
    finding's required action precisely because a comparator that cannot date its own
    evidence answers about the past.
    """
    admissible, reason = drift.observation_age_admissible(None, NOW)
    assert not admissible
    assert "no timestamp" in reason


def test_a_fresh_observation_is_admissible() -> None:
    taken = (NOW - timedelta(seconds=30)).isoformat()
    admissible, reason = drift.observation_age_admissible(taken, NOW)
    assert admissible
    assert "30s old" in reason


def test_an_observation_past_the_limit_is_refused() -> None:
    taken = (NOW - timedelta(seconds=drift.DEFAULT_MAX_AGE_SECONDS + 1)).isoformat()
    admissible, reason = drift.observation_age_admissible(taken, NOW)
    assert not admissible
    assert "as it was, not as it is" in reason


def test_the_boundary_second_is_still_admissible() -> None:
    taken = (NOW - timedelta(seconds=drift.DEFAULT_MAX_AGE_SECONDS)).isoformat()
    assert drift.observation_age_admissible(taken, NOW)[0]


def test_a_naive_timestamp_is_refused_rather_than_assumed_utc() -> None:
    """Assuming a timezone silently shifts the age by hours in either direction."""
    admissible, reason = drift.observation_age_admissible("2026-08-05T12:00:00", NOW)
    assert not admissible
    assert "no timezone" in reason


def test_a_future_timestamp_is_refused() -> None:
    """A clock nobody can reason about, and the way a replay is made to look fresh."""
    taken = (NOW + timedelta(minutes=5)).isoformat()
    admissible, reason = drift.observation_age_admissible(taken, NOW)
    assert not admissible
    assert "in the future" in reason


def test_a_malformed_timestamp_is_refused() -> None:
    admissible, reason = drift.observation_age_admissible("yesterday", NOW)
    assert not admissible
    assert "not an ISO instant" in reason


def test_the_script_stamps_the_observation_where_it_is_taken(tmp_path: Path) -> None:
    observation = tmp_path / "observed.json"
    assert _run("--observe", str(ROOT), "--out", str(observation)).returncode == 0
    payload = json.loads(observation.read_text(encoding="utf-8"))

    taken = datetime.fromisoformat(payload["observed_at"])
    assert taken.tzinfo is not None
    assert abs((datetime.now(UTC) - taken).total_seconds()) < 300


def test_the_script_refuses_a_stale_observation_instead_of_comparing_it(
    tmp_path: Path,
) -> None:
    observation = tmp_path / "observed.json"
    assert _run("--observe", str(ROOT), "--out", str(observation)).returncode == 0
    payload = json.loads(observation.read_text(encoding="utf-8"))
    payload["observed_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    observation.write_text(json.dumps(payload), encoding="utf-8")

    checked = _run("--observation", str(observation))
    # 2, not 1: the environment is not known to have drifted, the evidence is unusable.
    assert checked.returncode == 2
    assert "as it was, not as it is" in json.loads(checked.stdout)["reason"]


def test_the_script_creates_the_directory_it_was_told_to_write_into(tmp_path: Path) -> None:
    """A fresh checkout has no var/.

    The first CI run of this check died on FileNotFoundError before it compared
    anything, and the job's own artefact list then reported four files as missing —
    the failure three steps from its cause. Asking every caller to mkdir first is how
    a check ends up wrapped in a shell line that swallows its exit code.
    """
    observation = tmp_path / "does" / "not" / "exist" / "observed.json"

    assert _run("--observe", str(ROOT), "--out", str(observation)).returncode == 0
    assert observation.is_file()
