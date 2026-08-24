from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.api.tests.security_fixtures import (
    write_calibration_bundle,
    write_corpus_governance_profile,
    write_entitlement_profile,
    write_reviewer_registry,
    write_source_trust_profile,
)
from scripts.gcp.verify_governance_bundle import verify


def _bundle(tmp_path: Path) -> Path:
    write_entitlement_profile(tmp_path)
    write_source_trust_profile(tmp_path)
    write_reviewer_registry(tmp_path)
    write_corpus_governance_profile(tmp_path)
    write_calibration_bundle(tmp_path)
    return tmp_path


def test_valid_bundle_is_content_addressed(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    result = verify(root, oidc_issuer="https://id.example", oidc_audience="korpus-api")
    assert len(result["release_id"]) == 64
    assert result["acceptance"]["active_reviewer_subjects"] >= 2
    assert result["acceptance"]["calibration_ranking_valid"] is True
    assert result["acceptance"]["calibration_selective_answering_valid"] is True


def test_bundle_id_changes_when_entitlements_change(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    first = verify(root, oidc_issuer="https://id.example", oidc_audience="korpus-api")["release_id"]
    obj = json.loads((root / "entitlements.json").read_text(encoding="utf-8"))
    obj["profile_id"] = "test-entitlements-v2"
    (root / "entitlements.json").write_text(json.dumps(obj), encoding="utf-8")
    second = verify(root, oidc_issuer="https://id.example", oidc_audience="korpus-api")[
        "release_id"
    ]
    assert first != second


def test_oidc_binding_mismatch_fails_closed(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    with pytest.raises(ValueError, match="OIDC issuer"):
        verify(root, oidc_issuer="https://other.example", oidc_audience="korpus-api")


def test_calibration_artifact_tamper_fails_closed(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    with (root / "calibration-dataset.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"tampered":true}\n')
    with pytest.raises(ValueError, match="dataset digest mismatch"):
        verify(root, oidc_issuer="https://id.example", oidc_audience="korpus-api")
