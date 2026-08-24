from __future__ import annotations

import json

import pytest

from scripts.gcp import candidate_target, probe_candidate, traffic_snapshot


def test_traffic_snapshot_emits_revision_map() -> None:
    payload = {
        "status": {
            "traffic": [
                {"revisionName": "api-00002", "percent": 20},
                {"revisionName": "api-00001", "percent": 80},
            ]
        }
    }
    assert traffic_snapshot.canonical_allocations(payload) == {"api-00001": 80, "api-00002": 20}
    assert traffic_snapshot.canonical_traffic(payload) == "api-00001=80,api-00002=20"


def test_candidate_target_requires_one_immutable_tagged_revision() -> None:
    payload = {
        "status": {
            "traffic": [
                {"revisionName": "api-00001", "percent": 100},
                {
                    "revisionName": "api-00002",
                    "percent": 0,
                    "tag": "candidate",
                    "url": "https://candidate---api-xyz.run.app",
                },
            ]
        }
    }
    assert candidate_target.candidate(payload) == {
        "tag": "candidate",
        "revision": "api-00002",
        "url": "https://candidate---api-xyz.run.app",
        "percent": 0,
    }
    with pytest.raises(ValueError):
        candidate_target.candidate({"status": {"traffic": []}})
    for revision, url in (
        ("API_BAD", "https://candidate---api-xyz.run.app"),
        ("api-r2", "https://evil.example"),
    ):
        with pytest.raises(ValueError):
            candidate_target.candidate(
                {
                    "status": {
                        "traffic": [
                            {"revisionName": revision, "percent": 0, "tag": "candidate", "url": url}
                        ]
                    }
                }
            )


def test_probe_rejects_non_run_app_targets() -> None:
    for bad in (
        "http://x.run.app",
        "https://user:pass@x.run.app",
        "https://evil.example",
        "https://x.run.app?token=x",
    ):
        with pytest.raises(ValueError):
            probe_candidate.evaluate(bad, "https://web.run.app", attempts=1, timeout=1)


def test_probe_requires_exact_ready_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = iter(
        [
            (200, json.dumps({"status": "ready"}).encode()),
            (200, b"ok"),
            (200, json.dumps({"status": "ready", "audit_head": 1}).encode()),
            (200, b"ok"),
        ]
    )
    monkeypatch.setattr(probe_candidate, "_get", lambda url, timeout: next(replies))
    checks = probe_candidate.evaluate(
        "https://candidate---api-xyz.run.app",
        "https://candidate---web-xyz.run.app",
        attempts=2,
        timeout=1,
    )
    assert [item.passed for item in checks] == [True, True, False, True]
