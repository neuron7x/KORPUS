from __future__ import annotations

from pathlib import Path

from scripts.manifest_paths import source_included

ROOT = Path(__file__).resolve().parents[3]


def test_package_producer_excludes_git_history_by_construction() -> None:
    producer = (ROOT / "scripts/package_repository.sh").read_text(encoding="utf-8")
    assert "git bundle" not in producer
    assert 'git archive --format=tar "$source_commit"' in producer
    assert '"history_included":false' in producer
    assert "git rev-parse HEAD" in producer


def test_only_formal_production_promotion_requires_the_release_tag() -> None:
    producer = (ROOT / "scripts/package_repository.sh").read_text(encoding="utf-8")
    promotion = (ROOT / "scripts/package_production_release.sh").read_text(encoding="utf-8")
    assert "check_release_identity.py --require-git-tag" not in producer
    assert "check_release_identity.py --require-git-tag" in promotion


def test_package_only_metadata_cannot_expand_source_authority() -> None:
    for path in (
        "PACKAGE_BUILD.json",
        "FULL_SSOT_PACKAGE_RECEIPT.json",
        "PACKAGE_BOUNDARY.md",
        "CANONICAL_RELEASE_REPORT.json",
        "reports/RESEARCH_ASSURANCE_REPORT.json",
        "evidence/sealed.json",
    ):
        assert source_included(Path(path)) is False
    assert source_included(Path("docs/PACKAGE_BUILD.json")) is True
