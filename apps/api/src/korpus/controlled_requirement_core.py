"""Small, reusable predicates used by the controlled-environment requirement ledger."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

ALL_RUNTIME_ROLES = frozenset({"api", "worker"})
API_ONLY = frozenset({"api"})
WORKER_ONLY = frozenset({"worker"})


@dataclass(frozen=True)
class ControlledRequirement:
    name: str
    holds: Callable[[Any], bool]
    message: str
    roles: frozenset[str] = ALL_RUNTIME_ROLES

    def applies_to(self, settings: Any) -> bool:
        return str(getattr(settings, "runtime_role", "api")) in self.roles

    def violated(self, settings: Any) -> bool:
        return self.applies_to(settings) and not self.holds(settings)


def verified_database_transport(settings: Any) -> bool:
    transport = str(settings.database_transport)
    normalized = str(settings.database_url).replace("postgresql+psycopg", "postgresql", 1)
    parsed = urlparse(normalized)
    if transport == "cloud_sql_socket":
        hosts = parse_qs(parsed.query).get("host", [])
        return parsed.hostname is None and len(hosts) == 1 and hosts[0].startswith("/cloudsql/")
    sslmode = parse_qs(parsed.query).get("sslmode", [""])[0]
    return transport == "direct_tls" and sslmode == "verify-full"


def browser_settings_present(settings: Any) -> bool:
    return all(
        (
            settings.oidc_authorization_endpoint,
            settings.oidc_token_endpoint,
            settings.oidc_client_id,
            settings.oidc_redirect_uri,
        )
    )


def file_present(path: Any) -> bool:
    return path is not None and path.is_file()
