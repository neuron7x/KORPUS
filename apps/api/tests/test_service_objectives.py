"""An objective nobody checks is a paragraph.

SRE-001 and INF-008 were external because there was nothing to measure. There is now, so
the promises are declared in `scripts/service_objectives.py` and judged against the load
probe's report — a change that makes the system slower fails a gate rather than a
conversation.

Three properties, and the third is the one that keeps the other two honest:

  * an objective that is met passes;
  * an objective that is missed fails, and names which;
  * a run with no measurements behind it is neither — it is UNMEASURED, its own state,
    and reporting it as a pass is how a green board comes to mean "nobody looked".

Executed 2026-08-06 against 1648 documents and 118 622 spans: p95 3.269 s at eight
concurrent, cold first request 0.834 s, no 5xx, no `retrieval_deadline_exceeded`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "scripts/service_objectives.py"


def _report(**overrides: Any) -> dict[str, Any]:
    """A load report shaped like the probe's, healthy unless a test says otherwise."""
    soak = {
        "concurrency": 8,
        "requests": 291,
        "p50_seconds": 0.974,
        "p95_seconds": 2.608,
        "statuses": {"200": 291},
        "decisions": {"extractive_claims_passed_calibrated_gates": 223},
    }
    soak.update(overrides.pop("soak", {}))
    return {
        "measured_at": "2026-08-06T00:00:00+00:00",
        "cold_first_request": {"seconds": 0.84, "status": "200"},
        "load": dict(soak),
        "spike": dict(soak),
        "soak": soak,
        **overrides,
    }


def _run(measurements: Path, out: Path) -> tuple[int, dict[str, Any]]:
    completed = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--measurements",
            str(measurements),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        env={**os.environ, "PATH": "/usr/bin:/bin"},
        timeout=300,
    )
    return completed.returncode, json.loads(completed.stdout)


def test_a_healthy_measurement_meets_every_objective(tmp_path: Path) -> None:
    measurements = tmp_path / "load.json"
    measurements.write_text(json.dumps(_report()), encoding="utf-8")

    code, result = _run(measurements, tmp_path / "objectives.json")

    assert code == 0, result
    assert result["status"] == "PASS"
    assert result["unmet"] == []


def test_an_unfinished_search_fails_the_objective(tmp_path: Path) -> None:
    """Not about speed. An unfinished search renders as "the corpus holds nothing"."""
    measurements = tmp_path / "load.json"
    measurements.write_text(
        json.dumps(
            _report(
                soak={
                    "decisions": {
                        "extractive_claims_passed_calibrated_gates": 55,
                        "retrieval_deadline_exceeded": 62,
                    }
                }
            )
        ),
        encoding="utf-8",
    )

    code, result = _run(measurements, tmp_path / "objectives.json")

    assert code != 0
    assert "search_completes" in result["unmet"], result["unmet"]


def test_a_server_error_fails_the_objective(tmp_path: Path) -> None:
    measurements = tmp_path / "load.json"
    measurements.write_text(
        json.dumps(_report(soak={"statuses": {"200": 280, "503": 11}})), encoding="utf-8"
    )

    code, result = _run(measurements, tmp_path / "objectives.json")

    assert code != 0
    assert "answers_are_delivered" in result["unmet"]


def test_latency_beyond_the_objective_fails(tmp_path: Path) -> None:
    measurements = tmp_path / "load.json"
    measurements.write_text(json.dumps(_report(soak={"p95_seconds": 21.4})), encoding="utf-8")

    code, result = _run(measurements, tmp_path / "objectives.json")

    assert code != 0
    assert "answer_latency_steady" in result["unmet"]


def test_no_measurement_is_unmeasured_and_not_a_pass(tmp_path: Path) -> None:
    """The control. A green board that means "nobody looked" is worse than a red one."""
    code, result = _run(tmp_path / "absent.json", tmp_path / "objectives.json")

    assert code == 2, result
    assert result["status"] == "UNMEASURED"
    assert result["status"] != "PASS"


def test_every_objective_carries_the_conditions_it_was_judged_under(tmp_path: Path) -> None:
    """A p95 without a concurrency is a claim about somebody else's hardware."""
    measurements = tmp_path / "load.json"
    measurements.write_text(json.dumps(_report()), encoding="utf-8")

    _, result = _run(measurements, tmp_path / "objectives.json")

    for objective in result["objectives"]:
        assert objective["rationale"], objective["name"]
        assert "phase" in objective["conditions"], objective["name"]


def test_subject_throttling_under_rated_load_fails_capacity_objective(tmp_path: Path) -> None:
    measurements = tmp_path / "load.json"
    measurements.write_text(
        json.dumps(_report(soak={"refusal_reasons": {"subject_share_exhausted": 1}})),
        encoding="utf-8",
    )
    code, result = _run(measurements, tmp_path / "objectives.json")
    assert code != 0
    assert "rated_capacity_is_honest" in result["unmet"]
