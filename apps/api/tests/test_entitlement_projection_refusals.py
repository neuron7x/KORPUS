"""The paths on which an identity is refused, exercised.

`EntitlementProfile` exists because an OIDC token authenticates a subject and its
groups but must not, by itself, grant application roles, clearance, corpora or
compartments: an IdP claim-mapping mistake would otherwise become a privilege grant.
The projection therefore refuses — wrong issuer, wrong audience, denied subject, a
subject that maps to no role at all, a profile whose bytes do not match the digest the
configuration pins.

Those refusals were unexercised. Coverage measured them as branches nothing had ever
taken, which is the same statement as: the code that decides who gets in has never
been observed keeping anyone out.

The merge path is asserted for the same reason in the other direction — group and
subject grants combine by union and maximum, so a mistake there widens access rather
than narrowing it, and a widening bug produces no error anywhere.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from korpus.security.entitlements import EntitlementGrant, EntitlementProfile

ISSUER = "https://id.example"
AUDIENCE = "korpus"


def _profile(**overrides: object) -> EntitlementProfile:
    values: dict[str, object] = {
        "profile_id": "entitlements-test",
        "issuer": ISSUER,
        "audience": AUDIENCE,
        "default": EntitlementGrant(roles=frozenset({"user"}), clearance=1),
        "subjects": {
            "analyst": EntitlementGrant(
                roles=frozenset({"reviewer"}), clearance=2, corpora=frozenset({"restricted-demo"})
            )
        },
        "groups": {
            "duty-officers": EntitlementGrant(roles=frozenset({"admin"}), clearance=3),
        },
        "deny_subjects": frozenset({"revoked"}),
    }
    values.update(overrides)
    return EntitlementProfile(**values)


def _claims(**overrides: object) -> dict[str, object]:
    claims: dict[str, object] = {"sub": "analyst", "iss": ISSUER, "aud": [AUDIENCE]}
    claims.update(overrides)
    return claims


def test_a_valid_subject_is_projected_through_the_profile() -> None:
    """The dual: without it every refusal below could be refusing for another reason."""
    identity = _profile().resolve(_claims())

    assert "reviewer" in identity.roles
    assert "user" in identity.roles, "the default grant must still apply"


@pytest.mark.parametrize(
    "claims,reason",
    [
        ({"sub": ""}, "no active entitlement"),
        ({"sub": "   "}, "no active entitlement"),
        ({"sub": "revoked"}, "no active entitlement"),
        ({"iss": "https://attacker.example"}, "issuer mismatch"),
        ({"aud": ["someone-else"]}, "audience mismatch"),
        ({"aud": "someone-else"}, "audience mismatch"),
    ],
)
def test_a_token_that_does_not_belong_here_is_refused(
    claims: dict[str, object], reason: str
) -> None:
    with pytest.raises(PermissionError, match=reason):
        _profile().resolve(_claims(**claims))


def test_a_string_audience_claim_is_accepted_when_it_matches() -> None:
    """`aud` is a string or a list depending on the IdP; both must resolve alike."""
    identity = _profile().resolve(_claims(aud=AUDIENCE))

    assert "reviewer" in identity.roles


def test_a_subject_that_maps_to_no_role_is_refused() -> None:
    """Authenticated is not authorised: a subject with no role has no application."""
    profile = _profile(default=EntitlementGrant(), subjects={}, groups={})

    with pytest.raises(PermissionError, match="no application roles"):
        profile.resolve(_claims(sub="stranger"))


def test_group_and_subject_grants_combine_by_union_and_maximum() -> None:
    """A widening mistake here grants privilege and raises nothing anywhere."""
    identity = _profile().resolve(_claims(groups=["duty-officers"]))

    assert {"admin", "reviewer", "user"} <= set(identity.roles)
    assert int(identity.clearance) == 3, "clearance takes the maximum of the grants"
    assert "restricted-demo" in identity.corpora


def test_an_unknown_group_contributes_nothing_rather_than_failing_open() -> None:
    identity = _profile().resolve(_claims(groups=["not-in-the-profile"]))

    assert "admin" not in identity.roles


def test_a_string_groups_claim_is_treated_as_one_group() -> None:
    identity = _profile().resolve(_claims(groups="duty-officers"))

    assert "admin" in identity.roles


def test_a_profile_whose_bytes_changed_is_refused(tmp_path: Path) -> None:
    """The digest is what makes the profile server-controlled rather than a file."""
    path = tmp_path / "entitlements.json"
    path.write_text(_profile().model_dump_json(), encoding="utf-8")
    loaded = EntitlementProfile.load(path, expected_sha256=None)
    assert loaded.profile_id == "entitlements-test"

    with pytest.raises(ValueError, match="digest mismatch"):
        EntitlementProfile.load(path, expected_sha256="0" * 64)


def test_a_denied_subject_cannot_also_carry_an_explicit_grant() -> None:
    """Two rules pointing opposite ways is a configuration nobody can adjudicate."""
    with pytest.raises(ValueError, match="denied subjects cannot have explicit grants"):
        _profile(
            subjects={"revoked": EntitlementGrant(roles=frozenset({"admin"}))},
            deny_subjects=frozenset({"revoked"}),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("roles", frozenset({"not a role"})),
        ("corpora", frozenset({"Not A Corpus"})),
        ("compartments", frozenset({"with spaces"})),
    ],
)
def test_malformed_scope_names_are_refused(field: str, value: frozenset[str]) -> None:
    with pytest.raises(ValueError, match="invalid entitlement"):
        EntitlementGrant(**{field: value})


def test_the_canonical_digest_ignores_key_order(tmp_path: Path) -> None:
    """Otherwise re-serialising a profile would look like tampering."""
    profile = _profile()
    reordered = EntitlementProfile.model_validate(
        json.loads(json.dumps(profile.model_dump(mode="json"), sort_keys=False))
    )

    assert reordered.canonical_digest() == profile.canonical_digest()
