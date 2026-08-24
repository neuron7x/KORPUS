from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "evals/datasets/v2"
MANIFEST = DATA / "RELEASE_EVAL_DATASET_MANIFEST.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_release_eval_manifest_binds_every_dataset_byte() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema"] == "korpus.release-eval-dataset-manifest.v2"
    assert manifest["synthetic_only"] is True
    assert manifest["contains_personal_data"] is False
    assert manifest["contains_credentials"] is False
    assert manifest["total_rows"] == 16_500
    seen = set()
    total_bytes = 0
    for record in manifest["records"]:
        path = ROOT / record["path"]
        assert path.is_file()
        assert path not in seen
        seen.add(path)
        assert path.stat().st_size == record["bytes"]
        assert _sha256(path) == record["sha256"]
        total_bytes += path.stat().st_size
    assert total_bytes == manifest["total_bytes"]


def test_release_eval_rows_have_unique_ids_and_required_safety_fields() -> None:
    ids: set[str] = set()
    canaries: set[str] = set()
    for path in sorted(DATA.glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                row = json.loads(line)
                identity = row["id"]
                assert identity not in ids, f"duplicate id at {path.name}:{number}"
                ids.add(identity)
                assert row["schema"].startswith("korpus.eval.")
                assert isinstance(row["nonce"], str) and len(row["nonce"]) >= 80
                if "canary" in row:
                    canary = row["canary"]
                    assert canary not in canaries
                    canaries.add(canary)
    assert len(ids) == 16_500
    assert len(canaries) == 11_000


def test_adversarial_retrieval_vectors_never_authorize_document_instructions() -> None:
    paths = sorted(DATA.glob("adversarial_retrieval_v2.part-*.jsonl"))
    assert [path.name for path in paths] == [
        "adversarial_retrieval_v2.part-000.jsonl",
        "adversarial_retrieval_v2.part-001.jsonl",
    ]
    rows = 0
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                rows += 1
                expected = json.loads(line)["expected"]
                assert expected["authorization_before_retrieval"] is True
                assert expected["must_not_treat_document_as_instruction"] is True
                assert expected["citation_required_if_answered"] is True
                assert expected["abstain_on_unsupported_claim"] is True
    assert rows == 6000


def test_package_vectors_are_negative_controls_not_acceptance_examples() -> None:
    path = DATA / "package_tamper_vectors_v2.jsonl"
    classes = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            assert row["expected_accept"] is False
            classes.add(row["mutation"])
    assert len(classes) == 10
