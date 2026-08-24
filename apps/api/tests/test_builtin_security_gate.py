from __future__ import annotations

from pathlib import Path

from scripts.run_builtin_security_gate import evaluate


def _tree(tmp_path: Path, source: str) -> Path:
    root = tmp_path / "tree"
    (root / "apps/api/src/korpus").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "apps/api/src/korpus/release.json").write_text(
        '{"schema":"korpus.release-identity.v1","product":"KORPUS","version":"0.4.0","tag":"v0.4.0","artifact_stem":"KORPUS_SYSTEM_v0.4.0"}\n',
        encoding="utf-8",
    )
    (root / "apps/api/src/korpus/module.py").write_text(source, encoding="utf-8")
    return root


def test_clean_source_passes_builtin_security_gate(tmp_path: Path, monkeypatch) -> None:
    root = _tree(tmp_path, "def safe(value: str) -> str:\n    return value.strip()\n")
    monkeypatch.setattr("scripts.run_builtin_security_gate.release_tag", lambda: "v0.4.0")
    assert evaluate(root)["status"] == "PASS"


def test_shell_true_is_destroyed(tmp_path: Path, monkeypatch) -> None:
    root = _tree(
        tmp_path, "import subprocess\ndef bad(x: str):\n    return subprocess.run(x, shell=True)\n"
    )
    monkeypatch.setattr("scripts.run_builtin_security_gate.release_tag", lambda: "v0.4.0")
    report = evaluate(root)
    assert report["status"] == "FAIL"
    assert any(item["rule"] == "subprocess_shell_true" for item in report["findings"])


def test_high_confidence_secret_is_destroyed(tmp_path: Path, monkeypatch) -> None:
    root = _tree(tmp_path, 'TOKEN = "github_pat_abcdefghijklmnopqrstuvwxyz123456"\n')
    monkeypatch.setattr("scripts.run_builtin_security_gate.release_tag", lambda: "v0.4.0")
    report = evaluate(root)
    assert report["status"] == "FAIL"
    assert any(str(item["rule"]).startswith("hardcoded_") for item in report["findings"])
