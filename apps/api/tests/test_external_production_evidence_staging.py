from __future__ import annotations
from pathlib import Path
import pytest
import scripts.stage_external_production_evidence as staging


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for specs in staging.GROUPS.values():
        for env, _ in specs:
            monkeypatch.delenv(env, raising=False)


def test_no_external_evidence_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    result = staging.stage()
    assert result["status"] == "NO_EXTERNAL_EVIDENCE"
    assert all(group["status"] == "NO_EXTERNAL_EVIDENCE" for group in result["groups"])


def test_partial_group_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    env, _ = staging.GROUPS["tevv"][0]
    source = tmp_path / "tevv.json"; source.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(env, str(source))
    with pytest.raises(ValueError, match="external tevv evidence is partial"):
        staging.stage()


def test_complete_group_is_staged_but_not_declared_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch); monkeypatch.setattr(staging, "ROOT", tmp_path)
    specs = []
    for index, (env, _) in enumerate(staging.GROUPS["redteam"]):
        source = tmp_path / f"source-{index}.json"; source.write_text(f'{{"i":{index}}}', encoding="utf-8")
        destination = tmp_path / "var" / "production" / f"dest-{index}.json"
        monkeypatch.setenv(env, str(source)); specs.append((env, destination))
    monkeypatch.setitem(staging.GROUPS, "redteam", tuple(specs))
    result = staging.stage()
    redteam = next(item for item in result["groups"] if item["group"] == "redteam")
    assert redteam["status"] == "STAGED_FOR_VERIFICATION"
    assert "valid" not in redteam and "pass" not in redteam
