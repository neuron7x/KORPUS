from __future__ import annotations

import json
from pathlib import Path

import pytest
from korpus.application.assurance_trust import trusted_fingerprints
from korpus.release import RELEASE_TAG

CI_ENVIRONMENT = (
    "CI",
    "GITHUB_ACTIONS",
    "GITHUB_EVENT_NAME",
    "GITHUB_SERVER_URL",
    "GITHUB_REPOSITORY",
    "GITHUB_REPOSITORY_ID",
    "GITHUB_REPOSITORY_OWNER_ID",
    "GITHUB_REF_PROTECTED",
    "GITHUB_REF_TYPE",
    "GITHUB_REF_NAME",
    "GITHUB_REF",
    "GITHUB_SHA",
    "GITHUB_WORKFLOW_REF",
    "RUNNER_ENVIRONMENT",
    "GITLAB_CI",
    "CI_COMMIT_REF_PROTECTED",
)


def _clear_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in CI_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)


def _canonical_github_context(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "CI": "true",
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "neuron7x/KORPUS",
        "GITHUB_REPOSITORY_ID": "1332311807",
        "GITHUB_REPOSITORY_OWNER_ID": "206596321",
        "GITHUB_REF_PROTECTED": "true",
        "GITHUB_REF_TYPE": "tag",
        "GITHUB_REF_NAME": RELEASE_TAG,
        "GITHUB_REF": f"refs/tags/{RELEASE_TAG}",
        "GITHUB_SHA": "e" * 40,
        "GITHUB_WORKFLOW_REF": (
            f"neuron7x/KORPUS/.github/workflows/release.yml@refs/tags/{RELEASE_TAG}"
        ),
        "RUNNER_ENVIRONMENT": "github-hosted",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_runtime_trust_root_can_be_injected_without_mutating_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This is the non-CI runtime contract; remove ambient runner state explicitly.
    _clear_ci(monkeypatch)
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


def test_runtime_trust_root_is_refused_on_unprotected_github_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "trust.json"
    config.write_text(json.dumps({"field": []}), encoding="utf-8")
    monkeypatch.setenv("KORPUS_TRUST", "c" * 64)
    _canonical_github_context(monkeypatch)
    monkeypatch.setenv("GITHUB_REF_PROTECTED", "false")
    with pytest.raises(ValueError, match="protected canonical GitHub"):
        trusted_fingerprints(config, "field", "KORPUS_TRUST")


def test_runtime_trust_root_is_admitted_on_protected_canonical_github_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "trust.json"
    config.write_text(json.dumps({"field": []}), encoding="utf-8")
    fingerprint = "d" * 64
    monkeypatch.setenv("KORPUS_TRUST", fingerprint)
    _canonical_github_context(monkeypatch)
    assert trusted_fingerprints(config, "field", "KORPUS_TRUST") == {fingerprint}


def test_runtime_trust_root_is_refused_on_legacy_gitlab_even_when_protected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_ci(monkeypatch)
    config = tmp_path / "trust.json"
    config.write_text(json.dumps({"field": []}), encoding="utf-8")
    monkeypatch.setenv("KORPUS_TRUST", "f" * 64)
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITLAB_CI", "true")
    monkeypatch.setenv("CI_COMMIT_REF_PROTECTED", "true")
    with pytest.raises(ValueError, match="protected canonical GitHub"):
        trusted_fingerprints(config, "field", "KORPUS_TRUST")


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("GITHUB_REPOSITORY", "attacker/KORPUS"),
        ("GITHUB_REPOSITORY_ID", "1"),
        ("GITHUB_REPOSITORY_OWNER_ID", "1"),
        ("GITHUB_REF", "refs/tags/v0.9.8"),
        ("GITHUB_SHA", "not-a-full-sha"),
        ("RUNNER_ENVIRONMENT", "self-hosted"),
        ("GITHUB_WORKFLOW_REF", "neuron7x/KORPUS/.github/workflows/release.yml@refs/heads/main"),
    ],
)
def test_runtime_trust_root_is_refused_when_github_identity_is_incoherent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    config = tmp_path / "trust.json"
    config.write_text(json.dumps({"field": []}), encoding="utf-8")
    monkeypatch.setenv("KORPUS_TRUST", "1" * 64)
    _canonical_github_context(monkeypatch)
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match="protected canonical GitHub"):
        trusted_fingerprints(config, "field", "KORPUS_TRUST")
