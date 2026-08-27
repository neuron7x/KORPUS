from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "audit_corpus_admission", ROOT / "scripts/audit_corpus_admission.py"
)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def _entry(path: Path, **changes: object) -> dict[str, object]:
    entry = {
        "file": path.name,
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "canonical_title": "Canonical",
        "issuer": "Issuer",
        "revision": "1",
        "authority": "analytical",
        "data_owner_id": "owner-1",
        "rights_reference": "RIGHTS-1",
        "rights_status": "authorized",
        "classification": "public",
        "releasability": "public",
        "retention_policy_id": "RET-1",
        "access_policy_id": "ACCESS-1",
        "source_uri": "https://example.test/source",
    }
    entry.update(changes)
    return entry


def test_complete_manifest_is_byte_bound_and_admissible(tmp_path: Path) -> None:
    document = tmp_path / "source.txt"
    document.write_text("evidence", encoding="utf-8")

    result = audit.evaluate({"documents": [_entry(document)]}, tmp_path)

    assert result["status"] == "PASS"
    assert result["admission_ratio"] == 1.0


def test_hash_drift_and_missing_governance_fail_closed(tmp_path: Path) -> None:
    document = tmp_path / "source.txt"
    document.write_text("evidence", encoding="utf-8")
    entry = _entry(document, source_sha256="0" * 64, data_owner_id="REVIEW_REQUIRED")

    result = audit.evaluate({"review_sentinel": "REVIEW_REQUIRED", "documents": [entry]}, tmp_path)

    assert result["status"] == "FAIL"
    assert result["issue_counts"] == {"GOVERNANCE_INCOMPLETE": 1, "HASH_MISMATCH": 1}


def test_unlisted_file_duplicate_content_and_symlink_are_refused(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    link = tmp_path / "link.txt"
    first.write_text("same", encoding="utf-8")
    second.write_text("same", encoding="utf-8")
    link.symlink_to(first)

    result = audit.evaluate({"documents": [_entry(first), _entry(second), _entry(link)]}, tmp_path)

    assert result["status"] == "FAIL"
    assert result["issue_counts"]["DUPLICATE_CONTENT"] == 1
    assert result["issue_counts"]["FILE_BOUNDARY"] == 1


def test_path_traversal_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    result = audit.evaluate({"documents": [_entry(outside, file="../outside.txt")]}, root)

    assert result["issue_counts"]["FILE_BOUNDARY"] == 1
