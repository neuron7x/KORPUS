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

    def __init__(self, posture: EgressPosture = EgressPosture.EXTERNAL_ALLOWED) -> None:
        self.posture = posture

    @property
    def models_permitted(self) -> bool:
        return self.posture is not EgressPosture.MODEL_DISABLED

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
        """True only if every address this host resolves to is private or loopback.

        Every, not any: a name that resolves to one private and one public address is a
        name whose next lookup may return the public one. Resolution failure is not local —
        a host that cannot be resolved cannot be shown to be inside anything.
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
            if not (parsed.is_private or parsed.is_loopback or parsed.is_link_local):
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
