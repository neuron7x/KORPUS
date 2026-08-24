"""Request-scoped audit metadata that is safe to persist.

Raw credentials never enter this context.  A browser session cookie or bearer credential
is reduced to a one-way SHA-256 binding used only to correlate events from the same
credential without disclosing it.  Client version is metadata, never authorization.
"""

from __future__ import annotations

import hashlib
import re
from contextvars import ContextVar, Token
from dataclasses import dataclass

CLIENT_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9._+\-]{1,64}$")


@dataclass(frozen=True)
class RequestAuditContext:
    client_version: str
    session_binding: str | None
    offline_mode: bool = False


_current: ContextVar[RequestAuditContext | None] = ContextVar(
    "korpus_request_audit_context", default=None
)


def credential_binding(*, session_cookie: str | None, authorization: str | None) -> str | None:
    if session_cookie:
        return "session:" + hashlib.sha256(session_cookie.encode("utf-8")).hexdigest()
    if authorization:
        return "bearer:" + hashlib.sha256(authorization.encode("utf-8")).hexdigest()
    return None


def normalized_client_version(value: str | None) -> str:
    candidate = (value or "").strip()
    return candidate if CLIENT_VERSION_PATTERN.fullmatch(candidate) else "unknown"


def request_audit_context(
    *, session_cookie: str | None, authorization: str | None, client_version: str | None
) -> RequestAuditContext:
    return RequestAuditContext(
        client_version=normalized_client_version(client_version),
        session_binding=credential_binding(
            session_cookie=session_cookie, authorization=authorization
        ),
        offline_mode=False,
    )


def set_request_audit_context(value: RequestAuditContext) -> Token[RequestAuditContext | None]:
    return _current.set(value)


def reset_request_audit_context(token: Token[RequestAuditContext | None]) -> None:
    _current.reset(token)


def current_request_audit_context() -> RequestAuditContext:
    return _current.get() or RequestAuditContext(client_version="unknown", session_binding=None)
