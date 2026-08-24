from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    root = Path(__file__).resolve().parents[3]
    script = root / "scripts/check_import_cycles.py"
    spec = importlib.util.spec_from_file_location("check_import_cycles", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_internal_import_graph_is_acyclic() -> None:
    module = _module()
    assert module.strongly_connected(module.internal_graph()) == []


def test_cycle_detector_negative_control() -> None:
    module = _module()
    graph = {"a": {"b"}, "b": {"c"}, "c": {"a"}, "d": set()}
    assert module.strongly_connected(graph) == [["a", "b", "c"]]
