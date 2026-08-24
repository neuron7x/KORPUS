"""Revoking a subject's entitlement must take effect without a restart.

Destruction stage, MAJOR: `_load_entitlement_profile` was wrapped in `@lru_cache`, so
the profile was frozen for the lifetime of the process. Adding a subject to
`deny_subjects` on disk had no effect — the probe reported `REVOCATION IGNORED
['reviewer']`, and the same input without the cache produced `DENIED`. Nothing
invalidated the cache and `/ready` did not re-read the file.

A system that answers questions about restricted material has to be able to take a
reader out. "Restart the API" is not that: it is an outage, it needs an operator who
knows the revocation happened, and in the deployment topology under test the same
process serves every corpus.

Two configurations are asserted, because they fail differently. Without a pinned
digest the new profile is loaded and the subject is denied. With a pinned digest the
new content cannot match the pin — the process must refuse to serve that subject
rather than keep answering from the profile it happens to hold.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from korpus.config import Settings
from korpus.security.auth import _load_entitlement_profile, load_entitlement_profile
from korpus.security.entitlements import EntitlementGrant, EntitlementProfile


def _profile(deny: frozenset[str] = frozenset()) -> EntitlementProfile:
    return EntitlementProfile(
        profile_id="revocation-test-v1",
        issuer="https://id.example",
        audience="korpus-api",
        default=EntitlementGrant(roles=frozenset({"user"}), corpora=frozenset({"public"})),
        deny_subjects=deny,
    )


def _write(path: Path, profile: EntitlementProfile) -> str:
    raw = profile.model_dump_json().encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


CLAIMS = {"sub": "revoked-subject", "iss": "https://id.example", "aud": ["korpus-api"]}


def test_revocation_on_disk_denies_the_subject_without_a_restart(tmp_path: Path) -> None:
    path = tmp_path / "entitlements.json"
    _write(path, _profile())
    assert load_entitlement_profile(str(path), None).resolve(CLAIMS).subject == "revoked-subject"

    _write(path, _profile(frozenset({"revoked-subject"})))

    with pytest.raises(PermissionError):
        load_entitlement_profile(str(path), None).resolve(CLAIMS)


def test_a_pinned_digest_refuses_a_changed_profile_rather_than_serving_the_old_one(
    tmp_path: Path,
) -> None:
    path = tmp_path / "entitlements.json"
    digest = _write(path, _profile())
    assert load_entitlement_profile(str(path), digest).resolve(CLAIMS).subject == "revoked-subject"

    _write(path, _profile(frozenset({"revoked-subject"})))

    with pytest.raises(ValueError, match="digest mismatch"):
        load_entitlement_profile(str(path), digest)


def test_a_rewrite_with_identical_content_is_not_a_reload(tmp_path: Path) -> None:
    """Cache invalidation keys on content, so touching the file changes nothing.

    Stated so the fix cannot degenerate into reading the profile on every request:
    that would put a file read and a JSON parse on the authentication path of every
    call, which is how the cache came to exist in the first place.
    """
    path = tmp_path / "entitlements.json"
    _write(path, _profile())
    first = load_entitlement_profile(str(path), None)
    path.write_bytes(path.read_bytes())

    assert load_entitlement_profile(str(path), None) is first


def test_the_cached_loader_is_not_reachable_with_a_stale_key(tmp_path: Path) -> None:
    """The underlying lru_cache is keyed on content, not on the path alone."""
    path = tmp_path / "entitlements.json"
    raw = path.write_bytes(_profile().model_dump_json().encode("utf-8"))
    del raw
    content_key = hashlib.sha256(path.read_bytes()).hexdigest()

    cached = _load_entitlement_profile(str(path), None, content_key)

    _write(path, _profile(frozenset({"revoked-subject"})))
    new_key = hashlib.sha256(path.read_bytes()).hexdigest()
    assert new_key != content_key
    assert _load_entitlement_profile(str(path), None, new_key) is not cached


def test_settings_still_accept_a_profile_path(tmp_path: Path) -> None:
    """Guard against the fix drifting away from how the app actually loads it."""
    path = tmp_path / "entitlements.json"
    digest = _write(path, _profile())
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'x.db'}",
        object_root=tmp_path / "objects",
        audit_anchor_path=tmp_path / "anchor.json",
        audit_hmac_key="test-audit-key",
        auth_mode="oidc",
        bind_host="127.0.0.1",
        entitlement_profile_path=path,
        entitlement_profile_sha256=digest,
        oidc_issuer="https://id.example",
        oidc_audience="korpus-api",
        oidc_jwks=json.dumps({"keys": []}),
    )
    assert settings.entitlement_profile_path == path
