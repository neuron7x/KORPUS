from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/verify_source_manifest.py"
SPEC = importlib.util.spec_from_file_location("verify_source_manifest", SCRIPT)
assert SPEC and SPEC.loader
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def test_invalid_manifest_never_emits_a_supported_report(tmp_path: Path) -> None:
    release = tmp_path / "apps/api/src/korpus/release.json"
    release.parent.mkdir(parents=True)
    release.write_text(
        '{"schema":"x","product":"x","version":"9","tag":"v9",'
        '"artifact_stem":"x","distribution_artifact":"x.zip"}',
        encoding="utf-8",
    )
    report = VERIFY.bound_report(tmp_path)
    assert report["status"] == "FAIL"


def test_evidence_refresh_verifies_the_manifest_before_rendering_claims() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("evidence-refresh:", 1)[1].split("\n\n", 1)[0]
    ordered = (
        "generate_manifest.py",
        "verify_source_manifest.py --out reports/SOURCE_MANIFEST_VERIFICATION_CURRENT.json",
        "release-truth",
        "current-truth-verify",
    )
    positions = [recipe.index(item) for item in ordered]
    assert positions == sorted(positions)
