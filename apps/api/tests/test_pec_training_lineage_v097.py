from __future__ import annotations

from korpus.application.pec_training_lineage import validate_training_lineage


def receipt():
    return {
        "release": "v0.9.7",
        "profile": "prod-v1",
        "source_revision": "rev-7",
        "dataset_sha256": "a" * 64,
        "receipt_sha256": "b" * 64,
    }


def test_training_lineage_accepts_exact_binding():
    assert validate_training_lineage(
        receipt(),
        release="v0.9.7",
        profile="prod-v1",
        source_revision="rev-7",
        dataset_sha256="a" * 64,
    ).valid


def test_training_lineage_rejects_dataset_drift():
    v = validate_training_lineage(
        receipt(),
        release="v0.9.7",
        profile="prod-v1",
        source_revision="rev-7",
        dataset_sha256="c" * 64,
    )
    assert not v.valid and "dataset_sha256" in v.failures


def test_training_lineage_rejects_source_revision_drift():
    v = validate_training_lineage(
        receipt(),
        release="v0.9.7",
        profile="prod-v1",
        source_revision="rev-new",
        dataset_sha256="a" * 64,
    )
    assert not v.valid and "source_revision" in v.failures


def test_training_lineage_requires_receipt_digest_shape():
    r = receipt()
    r["receipt_sha256"] = "bad"
    v = validate_training_lineage(
        r, release="v0.9.7", profile="prod-v1", source_revision="rev-7", dataset_sha256="a" * 64
    )
    assert not v.valid and "receipt_sha256" in v.failures
