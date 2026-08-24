from __future__ import annotations

import json
from pathlib import Path

import pytest
from korpus.application.assurance_trust import trusted_fingerprints


def test_runtime_trust_root_can_be_injected_without_mutating_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This test exercises the non-CI runtime contract. GitLab exports GITLAB_CI
    # into the test process, so remove that ambient context explicitly instead
    # of making the assertion depend on where pytest happens to run.
    monkeypatch.delenv("GITLAB_CI", raising=False)
    monkeypatch.delenv("CI_COMMIT_REF_PROTECTED", raising=False)
    config = tmp_path / "trust.json"
    repo_fp = "a" * 64
    runtime_fp = "b" * 64
    config.write_text(json.dumps({"field": [repo_fp]}), encoding="utf-8")
    monkeypatch.setenv("KORPUS_TRUST", runtime_fp)
    assert trusted_fingerprints(config, "field", "KORPUS_TRUST") == {repo_fp, runtime_fp}


def test_invalid_runtime_trust_root_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "trust.json"
    config.write_text(json.dumps({"field": []}), encoding="utf-8")
    monkeypatch.setenv("KORPUS_TRUST", "not-a-sha256")
    with pytest.raises(ValueError, match="invalid trusted signer"):
        trusted_fingerprints(config, "field", "KORPUS_TRUST")


def test_empty_runtime_trust_does_not_create_trust(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "trust.json"
    config.write_text(json.dumps({"field": []}), encoding="utf-8")
    monkeypatch.delenv("KORPUS_TRUST", raising=False)
    assert trusted_fingerprints(config, "field", "KORPUS_TRUST") == set()


def test_runtime_trust_root_is_refused_on_unprotected_ci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "trust.json"
    config.write_text(json.dumps({"field": []}), encoding="utf-8")
    monkeypatch.setenv("KORPUS_TRUST", "c" * 64)
    monkeypatch.setenv("GITLAB_CI", "true")
    monkeypatch.setenv("CI_COMMIT_REF_PROTECTED", "false")
    with pytest.raises(ValueError, match="unprotected GitLab ref"):
        trusted_fingerprints(config, "field", "KORPUS_TRUST")


def test_runtime_trust_root_is_admitted_on_protected_ci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "trust.json"
    config.write_text(json.dumps({"field": []}), encoding="utf-8")
    fingerprint = "d" * 64
    monkeypatch.setenv("KORPUS_TRUST", fingerprint)
    monkeypatch.setenv("GITLAB_CI", "true")
    monkeypatch.setenv("CI_COMMIT_REF_PROTECTED", "true")
    assert trusted_fingerprints(config, "field", "KORPUS_TRUST") == {fingerprint}
