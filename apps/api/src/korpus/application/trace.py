"""The request identifier, carried to wherever the audit event is written.

An audit trail that can only be read whole is not readable: `verify_audit` walks the
entire chain and returns one verdict, which answers "was anything tampered with" and
nothing about what happened during one request. An investigator asking why a particular
answer was withheld had to export the table. The trace id ties the events of a single
request together, and it lives inside the hashed payload rather than in a column beside
it, so it cannot be re-attributed without breaking the chain.
"""

from __future__ import annotations

import re
from contextvars import ContextVar, Token

TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

_current_trace_id: ContextVar[str | None] = ContextVar("korpus_trace_id", default=None)


def set_trace_id(value: str | None) -> Token[str | None]:
    if value is not None and not TRACE_ID_PATTERN.fullmatch(value):
        raise ValueError("invalid trace id")
    return _current_trace_id.set(value)


def reset_trace_id(token: Token[str | None]) -> None:
    _current_trace_id.reset(token)


def current_trace_id() -> str | None:
    return _current_trace_id.get()
