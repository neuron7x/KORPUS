"""Whether this deployment may talk to a model outside it, decided in one place.

Two optional model calls exist in this system: the query planner reformulates a question,
and the composer arranges retrieved sentences and proposes an opening line. Both are
convenience, both are refused into the extractive path on any failure, and neither
produces a fact. What they do produce is an outbound HTTPS request carrying the soldier's
question — and in some deployments that request is the incident, whatever it returns.

Three postures, and the middle one is why this is an enum rather than a boolean:

  EXTERNAL_ALLOWED  a vendor API may be called. The default for a laptop and for the
                    public demonstration.
  LOCAL_ONLY        a model may be used if it is reachable without leaving the deployment.
                    An on-premise endpoint on a private address.
  MODEL_DISABLED    no model at all. Retrieval and extraction only.

The check is on the *URL*, before the client is constructed, because a policy consulted
after a request is a policy that has already leaked the question. `LOCAL_ONLY` is enforced
by parsing the host and refusing anything that is not a loopback or private address rather
than by matching a hostname: `internal.example.com` resolving to a public IP is the shape
of a mistake nobody catches by reading the config.
"""

from __future__ import annotations

import ipaddress
import socket
from enum import StrEnum
from urllib.parse import urlparse

from korpus.domain.models import AccessTier


class EgressPosture(StrEnum):
    EXTERNAL_ALLOWED = "external_allowed"
    LOCAL_ONLY = "local_only"
    MODEL_DISABLED = "model_disabled"


class EgressDenied(RuntimeError):
    """A model call was refused by policy. Carries the posture, so an operator can act."""

    reason = "model_egress_denied"

    def __init__(self, posture: EgressPosture, detail: str) -> None:
        self.posture = posture
        super().__init__(f"{posture.value}: {detail}")


class ModelEgressPolicy:
    """One decision, taken before a client exists."""

    def __init__(
        self,
        posture: EgressPosture = EgressPosture.EXTERNAL_ALLOWED,
        max_external_tier: AccessTier = AccessTier.PUBLIC,
    ) -> None:
        self.posture = posture
        #: The highest classification of *corpus material* that may be carried to a model
        #: which sits outside this deployment. The URL check above governs whether an
        #: endpoint may be reached at all; this governs what may be sent once it can be —
        #: a distinct question, because `external_allowed` reaches a vendor and a vendor
        #: sees whatever the composer sends it. Defaults to `PUBLIC`: only material a
        #: reader with no clearance could already see leaves the deployment. Raising it is
        #: a deliberate act (GOV-006), not a default, and it has no effect under
        #: `local_only`/`model_disabled`, where the material never leaves in the first
        #: place.
        self.max_external_tier = max_external_tier

    @property
    def models_permitted(self) -> bool:
        return self.posture is not EgressPosture.MODEL_DISABLED

    def permits_material(self, max_tier: AccessTier) -> bool:
        """Whether material classified up to `max_tier` may be sent to the model.

        Only `EXTERNAL_ALLOWED` carries anything out of the deployment; under the other
        two postures the model is either local or absent, so classification never leaves
        and this is unconditionally true. Under `EXTERNAL_ALLOWED` a vendor receives what
        the composer sends, so material above the ceiling is refused here — before the
        request is built, for the same reason `check` runs on the URL before the client
        exists: a policy consulted after the send has already leaked the passage.
        """
        if self.posture is not EgressPosture.EXTERNAL_ALLOWED:
            return True
        return int(max_tier) <= int(self.max_external_tier)

    def check(self, base_url: str | None) -> None:
        """Raise `EgressDenied` unless this URL may be called under the current posture."""
        if self.posture is EgressPosture.MODEL_DISABLED:
            raise EgressDenied(self.posture, "no model may be called in this deployment")
        if self.posture is EgressPosture.EXTERNAL_ALLOWED:
            return

        target = (base_url or "").strip()
        if not target:
            # LOCAL_ONLY with no endpoint configured means the vendor default, which is
            # the public internet. Refused rather than guessed at.
            raise EgressDenied(self.posture, "no local model endpoint is configured")
        parsed = urlparse(target)
        if parsed.scheme not in {"http", "https"}:
            raise EgressDenied(self.posture, f"unsupported scheme: {parsed.scheme or 'none'}")
        host = parsed.hostname
        if not host:
            raise EgressDenied(self.posture, "endpoint carries no host")
        if not self._is_local(host):
            raise EgressDenied(self.posture, f"{host} is not inside this deployment")

    @staticmethod
    def _is_local(host: str) -> bool:
        """True only if every address this host resolves to is a private or loopback host
        we would legitimately run a model on — and never a link-local address.

        Every, not any: a name that resolves to one private and one public address is a
        name whose next lookup may return the public one. Resolution failure is not local —
        a host that cannot be resolved cannot be shown to be inside anything.

        Link-local is refused explicitly and first, because it is the one "private" range
        that is an attack rather than a deployment: 169.254.169.254 is the cloud metadata
        endpoint, and reaching it exfiltrates the instance's credentials. It cannot be
        excluded by dropping a term from the accept check — Python's `is_private` reports
        169.254.0.0/16 and fe80::/10 as private too (verified 2026-08-08), so the accept
        check would let them through on its own. The rejection has to be stated.
        """
        try:
            addresses = {
                info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
            }
        except (OSError, UnicodeError):
            return False
        if not addresses:
            return False
        for address in addresses:
            try:
                parsed = ipaddress.ip_address(address)
            except ValueError:  # pragma: no cover - getaddrinfo returns parseable literals
                return False
            if parsed.is_link_local:
                return False
            if not (parsed.is_private or parsed.is_loopback):
                return False
        return True


def guarded(policy: ModelEgressPolicy, base_url: str | None) -> bool:
    """`True` if a model may be built for this endpoint; `False` if policy refuses it.

    The boolean form exists for the composition root, where a refusal means "run without a
    planner" rather than "fail the request". The raising form is what the call sites use,
    so a model that was somehow constructed anyway still cannot be reached.
    """
    try:
        policy.check(base_url)
    except EgressDenied:
        return False
    return True
