from __future__ import annotations

import pytest

from scripts.gcp.traffic_snapshot import canonical_traffic


def test_traffic_snapshot_is_revision_exact_and_sorted() -> None:
    payload = {
        "status": {
            "traffic": [
                {"revisionName": "korpus-api-00009", "percent": 20},
                {"revisionName": "korpus-api-00008", "percent": 80},
            ]
        }
    }
    assert canonical_traffic(payload) == "korpus-api-00008=80,korpus-api-00009=20"


def test_traffic_snapshot_ignores_zero_percent_tagged_candidate() -> None:
    payload = {
        "status": {
            "traffic": [
                {"revisionName": "korpus-api-00008", "percent": 100},
                {"revisionName": "korpus-api-00009", "percent": 0, "tag": "candidate"},
            ]
        }
    }
    assert canonical_traffic(payload) == "korpus-api-00008=100"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": {"traffic": []}},
        {"status": {"traffic": [{"revisionName": "a", "percent": 90}]}},
        {"status": {"traffic": [{"percent": 100}]}},
        {
            "status": {
                "traffic": [
                    {"revisionName": "a", "percent": -1},
                    {"revisionName": "b", "percent": 101},
                ]
            }
        },
    ],
)
def test_invalid_traffic_snapshot_fails_closed(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        canonical_traffic(payload)
