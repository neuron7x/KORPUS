from korpus.application.policy_evidence import answer_policy_decision_id
from korpus.application.request_audit_context import (
    credential_binding,
    normalized_client_version,
)
from korpus.domain.models import AccessTier, Identity


def identity() -> Identity:
    return Identity(
        subject="reader-7",
        roles=frozenset({"user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"beta", "alpha"}),
        compartments=frozenset({"ops"}),
    )


def test_policy_decision_id_is_deterministic_and_binds_policy_inputs() -> None:
    first = answer_policy_decision_id(identity(), ["beta", "alpha"])
    second = answer_policy_decision_id(identity(), ["beta", "alpha"])
    reordered = answer_policy_decision_id(identity(), ["alpha", "beta"])
    assert first == second
    assert first != reordered, "request order is part of the auditable decision input"
    assert first.startswith("pd1:") and len(first) == 68


def test_session_binding_never_contains_raw_credential() -> None:
    raw = "secret-session-token"
    bound = credential_binding(session_cookie=raw, authorization=None)
    assert bound is not None and bound.startswith("session:")
    assert raw not in bound
    assert credential_binding(session_cookie=None, authorization="Bearer abc") != bound


def test_client_version_is_bounded_metadata_not_free_text() -> None:
    assert normalized_client_version("v0.6.0-web") == "v0.6.0-web"
    assert normalized_client_version("../../inject") == "unknown"
    assert normalized_client_version("x" * 65) == "unknown"
