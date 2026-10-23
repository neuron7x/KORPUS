"""Assessor identity evidence must fail closed on missing or malformed attestations."""

from korpus.application.tevv_assessor import assessor_identity_valid


def test_missing_or_malformed_assessor_identity_is_rejected() -> None:
    for evidence in ({}, {"assessor": None}, {"assessor": []}, {"assessor": ""}):
        assert assessor_identity_valid(evidence) is False


def test_only_explicitly_independent_assessor_is_admitted() -> None:
    assessor = {
        "organization": "Independent Validation Lab",
        "assessor_id": "assessor-01",
        "independent_of_system_owner": True,
    }
    assert assessor_identity_valid({"assessor": assessor}) is True
    assessor["independent_of_system_owner"] = False
    assert assessor_identity_valid({"assessor": assessor}) is False
