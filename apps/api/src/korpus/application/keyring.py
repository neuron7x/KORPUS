"""Which key signed which audit event, so a key can be replaced without losing the chain.

AUD-003. Every event was signed with one key and verified with whatever key the process
happened to hold. Rotating it therefore invalidated the entire history at once: the
verifier recomputes each event's HMAC, and with a new key none of them match. The only way
to change the key was to stop being able to prove anything that happened before.

So an event records the id of the key that signed it, and verification uses the key the
event names. Rotation adds a key and makes it active; the previous ones stay in the ring,
able to verify and unable to sign. That is the dual-validation window — not a period of
time, but a set of keys the verifier will still honour, which is the property the window
was for.

Revocation is deliberately not deletion. A revoked key's events still verify — the bytes
did not change and the chain still links — and are reported as signed by a key that is no
longer trusted. Removing the key instead would turn "this was signed by something we no
longer trust" into "this cannot be verified", and those are different facts about the same
event. An investigator needs the first.

Fail-closed on the unknown: an event naming a key the ring does not hold is invalid, not
skipped. A verifier that ignored what it could not check would report a chain as intact
while its middle was unreadable.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field

#: What events written before key ids existed are attributed to. They were all signed with
#: the one key the deployment held, and calling that key by a name is what lets them keep
#: verifying after a rotation instead of becoming unattributable.
LEGACY_KEY_ID = "legacy-unversioned"

#: A key id ends up in every audit row and in operator commands. Kept to what is safe in
#: both places rather than to what a database column will accept.
_ALLOWED = set("abcdefghijklmnopqrstuvwxyz0123456789-_.")


class KeyRingError(ValueError):
    """Raised when a ring is asked for something it must not answer."""


def valid_key_id(candidate: str) -> bool:
    return (
        bool(candidate)
        and len(candidate) <= 64
        and all(character in _ALLOWED for character in candidate)
    )


@dataclass(frozen=True)
class AuditKeyRing:
    """The keys this deployment may verify with, and the one it signs with.

    Constructed rather than mutated: a ring that could gain a key at runtime is a ring
    whose contents at the moment of a verification are not the contents anyone reviewed.
    """

    keys: dict[str, bytes]
    active_key_id: str
    revoked: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.keys:
            raise KeyRingError("an empty key ring can neither sign nor verify")
        for key_id in self.keys:
            if not valid_key_id(key_id):
                raise KeyRingError(f"key id is not usable in an audit row or a command: {key_id!r}")
        if self.active_key_id not in self.keys:
            raise KeyRingError(f"the active key {self.active_key_id!r} is not in the ring")
        if self.active_key_id in self.revoked:
            # A revoked key that is still signing is the state where every new event is
            # written under a key nobody trusts, and nothing says so until someone reads
            # the ring.
            raise KeyRingError(f"the active key {self.active_key_id!r} is revoked")
        unknown = self.revoked - set(self.keys)
        if unknown:
            raise KeyRingError(f"revoked keys are not in the ring: {sorted(unknown)}")

    @classmethod
    def single(cls, material: bytes, key_id: str = LEGACY_KEY_ID) -> AuditKeyRing:
        """The ring a deployment that has never rotated has."""
        return cls(keys={key_id: material}, active_key_id=key_id)

    @property
    def active_key(self) -> bytes:
        return self.keys[self.active_key_id]

    def sign(self, message: bytes) -> tuple[str, str]:
        """The signature and the id of the key that made it, together, always."""
        return self.active_key_id, hmac.new(self.active_key, message, hashlib.sha256).hexdigest()

    def verify(self, key_id: str, message: bytes, signature: str) -> bool:
        """Whether this signature is what the named key produces for these bytes.

        An unknown key id is False rather than an exception: the caller is verifying a
        chain and needs to report *where* it stopped being verifiable, which a raised
        error hides behind a traceback.
        """
        material = self.keys.get(key_id or LEGACY_KEY_ID)
        if material is None:
            return False
        expected = hmac.new(material, message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def is_revoked(self, key_id: str) -> bool:
        return (key_id or LEGACY_KEY_ID) in self.revoked

    def describe(self) -> dict[str, object]:
        return {
            "active_key_id": self.active_key_id,
            "verifiable_key_ids": sorted(self.keys),
            "revoked_key_ids": sorted(self.revoked),
            "interpretation": (
                "Revoked keys remain in the ring on purpose. Their events still verify — "
                "the bytes did not change and the chain still links — and are reported as "
                "signed by a key that is no longer trusted. Removing the key would turn "
                "that into 'cannot be verified', which is a different fact about the same "
                "event, and the weaker one."
            ),
        }
