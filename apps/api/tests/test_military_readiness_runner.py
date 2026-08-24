from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _runner():
    path = ROOT / "scripts/run_military_readiness_campaign.py"
    spec = importlib.util.spec_from_file_location("military_readiness_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_regression_batches_cover_every_test_module_once() -> None:
    module = _runner()
    batches = module.regression_batches(8)
    observed = [item for _, command in batches for item in command[4:]]
    expected = [
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "apps/api/tests").glob("test_*.py"), key=lambda path: path.name)
    ]
    assert observed == expected
    assert len(observed) == len(set(observed))


def test_regression_batch_size_is_fail_closed() -> None:
    module = _runner()
    try:
        module.regression_batches(0)
    except ValueError:
        pass
    else:
        raise AssertionError("zero batch size must be rejected")


def test_aggregate_status_preserves_fail_and_unknown() -> None:
    module = _runner()
    assert module.aggregate_status([{"status": "PASS"}]) == "PASS"
    assert module.aggregate_status([{"status": "PASS"}, {"status": "UNKNOWN"}]) == "UNKNOWN"
    assert module.aggregate_status([{"status": "UNKNOWN"}, {"status": "FAIL"}]) == "FAIL"
