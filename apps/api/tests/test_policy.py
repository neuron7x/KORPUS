import pytest

from korpus.application.policy import AuthorizationError, PolicyEngine
from korpus.domain.models import AccessTier, Identity


def test_role_permissions_are_fail_closed():
    policy = PolicyEngine()
    identity = Identity(subject="x", roles=frozenset({"unknown-role"}), clearance=AccessTier.PUBLIC)
    with pytest.raises(AuthorizationError):
        policy.require(identity, "answer:read")


def test_requested_corpora_can_only_narrow_access(public_identity):
    policy = PolicyEngine()
    assert policy.resolve_corpora(public_identity, ["public"]) == frozenset({"public"})
    with pytest.raises(AuthorizationError):
        policy.resolve_corpora(public_identity, ["restricted-demo"])


def test_identity_rejects_malformed_roles_and_corpus_ids():
    with pytest.raises(ValueError, match="role"):
        Identity(subject="x", roles=frozenset({"Admin Role"}), corpora=frozenset({"public"}))
    with pytest.raises(ValueError, match="corpus"):
        Identity(subject="x", roles=frozenset({"user"}), corpora=frozenset({"../escape"}))
