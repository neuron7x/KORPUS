from __future__ import annotations

from korpus.application.supply_chain_attestation import (
    SLSA_PROVENANCE_V1,
    build_in_toto_statement,
    verify_in_toto_subject,
)


def statement(data=b"artifact"):
    return build_in_toto_statement(
        artifact_name="korpus.zip",
        artifact_bytes=data,
        builder_id="https://github.com/example/builder",
        source_uri="git+https://example/repo@v0.9.7",
        source_digest="a" * 64,
    )


def test_in_toto_statement_uses_slsa_v1_predicate():
    s = statement()
    assert s["predicateType"] == SLSA_PROVENANCE_V1


def test_in_toto_subject_verifies_exact_artifact_bytes():
    assert verify_in_toto_subject(
        statement(), artifact_name="korpus.zip", artifact_bytes=b"artifact"
    )


def test_in_toto_subject_rejects_artifact_mutation():
    assert not verify_in_toto_subject(
        statement(), artifact_name="korpus.zip", artifact_bytes=b"changed"
    )


def test_in_toto_subject_rejects_wrong_artifact_name():
    assert not verify_in_toto_subject(
        statement(), artifact_name="other.zip", artifact_bytes=b"artifact"
    )
