from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.gcp import rollback_traffic as rt


def test_validate_spec_requires_exact_immutable_distribution() -> None:
    assert rt.validate_spec("rev-b=20,rev-a=80") == "rev-a=80,rev-b=20"
    for bad in ("", "LATEST=100", "rev=90", "rev=50,rev=50", "rev=101", "rev=-1", "rev=abc"):
        with pytest.raises(ValueError):
            rt.validate_spec(bad)


def test_service_failure_writes_error_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rt.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=9, stdout="", stderr="denied"))
    evidence = tmp_path / "api.json"
    assert rt.rollback_service(project="p", region="r", service="korpus-api", spec="rev-a=100", evidence=evidence) is False
    payload = json.loads((tmp_path / "api.error.json").read_text())
    assert payload["returncode"] == 9


def test_main_attempts_web_even_when_api_rollback_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    def fake_run(args, **kwargs):
        service = args[4]; seen.append(service)
        if service == "korpus-api":
            return SimpleNamespace(returncode=7, stdout="", stderr="api failed")
        return SimpleNamespace(returncode=0, stdout='{"metadata":{"name":"korpus-web"}}', stderr="")
    monkeypatch.setattr(rt.subprocess, "run", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        ["rollback", "--project", "p", "--region", "r", "--api-spec", "api-r1=100", "--web-spec", "web-r1=100", "--output-dir", str(tmp_path)],
    )
    assert rt.main() == 1
    assert seen == ["korpus-api", "korpus-web"]
    assert (tmp_path / "api-rollback.error.json").is_file()
    assert (tmp_path / "web-rollback.json").is_file()


def test_empty_previous_traffic_is_not_applicable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rt.subprocess, "run", lambda *a, **k: pytest.fail("gcloud must not run"))
    evidence = tmp_path / "api.json"
    assert rt.rollback_service(project="p", region="r", service="korpus-api", spec="", evidence=evidence)
    assert json.loads(evidence.read_text())["rollback"] == "not-applicable"
