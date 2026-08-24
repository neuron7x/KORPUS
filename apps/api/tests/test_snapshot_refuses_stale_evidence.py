"""Promotion refuses evidence the operational gate did not hash.

The gate passes over specific bytes and records their sha256. Promotion copies var
artifacts into `reports/` as the release evidence. Nothing stopped a *different* file — a
stale one from an earlier run, a hand-edited one — being promoted beside the gate's PASS.
That is the "green next to a stale artifact" failure this whole project is built to refuse,
and it was live: a FAIL `operational-gate.json` once sat in var while a PASS assurance was
assembled from CI artifacts.

So `_verify_evidence_matches_the_gate` re-hashes each promoted artifact against
`evidence_sha256` and refuses on mismatch. This drives it directly rather than through the
whole pipeline, because the property is about the cross-check, not about a real gate run.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "snapshot_assurance", ROOT / "scripts/snapshot_assurance.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed(var: Path, contents: dict[str, str]) -> dict[str, str]:
    """Write the four evidence files and return their true digests."""
    digests = {}
    names = {
        "eval": "eval-report.json",
        "mutation": "mutation-report.json",
        "migration": "migration-report.json",
        "scale": "scale-report.json",
    }
    for key, filename in names.items():
        path = var / filename
        path.write_text(contents.get(key, f'{{"{key}": true}}'), encoding="utf-8")
        digests[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def test_matching_evidence_is_accepted(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    var = tmp_path / "var"
    var.mkdir()
    digests = _seed(var, {})
    (var / "operational-gate.json").write_text(
        json.dumps({"status": "PASS", "evidence_sha256": digests}), encoding="utf-8"
    )
    monkeypatch.setattr(module, "VAR", var)
    module._verify_evidence_matches_the_gate()  # must not raise


def test_a_promoted_file_the_gate_did_not_hash_is_refused(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    var = tmp_path / "var"
    var.mkdir()
    digests = _seed(var, {})
    (var / "operational-gate.json").write_text(
        json.dumps({"status": "PASS", "evidence_sha256": digests}), encoding="utf-8"
    )
    # The gate hashed one mutation report; a different one is now sitting in var.
    (var / "mutation-report.json").write_text('{"mutation": "tampered"}', encoding="utf-8")
    monkeypatch.setattr(module, "VAR", var)
    with pytest.raises(SystemExit, match="does not match the digest"):
        module._verify_evidence_matches_the_gate()


def test_a_gate_without_evidence_digests_cannot_be_trusted(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    var = tmp_path / "var"
    var.mkdir()
    _seed(var, {})
    (var / "operational-gate.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    monkeypatch.setattr(module, "VAR", var)
    with pytest.raises(SystemExit, match="no evidence_sha256"):
        module._verify_evidence_matches_the_gate()


def test_a_missing_hashed_artifact_is_refused(tmp_path: Path, monkeypatch) -> None:
    module = _load_module()
    var = tmp_path / "var"
    var.mkdir()
    digests = _seed(var, {})
    (var / "operational-gate.json").write_text(
        json.dumps({"status": "PASS", "evidence_sha256": digests}), encoding="utf-8"
    )
    (var / "scale-report.json").unlink()
    monkeypatch.setattr(module, "VAR", var)
    with pytest.raises(SystemExit, match=r"did not hash|refusing to promote"):
        module._verify_evidence_matches_the_gate()
