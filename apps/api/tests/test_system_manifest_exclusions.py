from __future__ import annotations

import importlib.util
from pathlib import Path


def _load(script: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_handoff_evidence_is_not_part_of_system_manifest_or_source_digest() -> None:
    root = Path(__file__).resolve().parents[3]
    manifest = _load(root / "scripts" / "build_system_manifest.py", "build_system_manifest")
    digest = _load(root / "scripts" / "source_digest.py", "source_digest")
    assert manifest._included("handoff/evidence/HANDOFF_VERIFICATION.json") is False
    assert digest._included("handoff/evidence/HANDOFF_VERIFICATION.json") is False
    assert manifest._included("handoff/machine/current_state.json") is True
    assert digest._included("handoff/machine/current_state.json") is True
