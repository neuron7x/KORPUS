from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token

from korpus.application.predictive_evidence_control import ControllerTrace

PECObserver = Callable[[ControllerTrace, float], None]
_OBSERVER: ContextVar[PECObserver | None] = ContextVar("korpus_pec_observer", default=None)


def set_pec_observer(observer: PECObserver | None) -> Token[PECObserver | None]:
    return _OBSERVER.set(observer)


def reset_pec_observer(token: Token[PECObserver | None]) -> None:
    _OBSERVER.reset(token)


def emit_pec_observation(trace: ControllerTrace | None, elapsed_seconds: float) -> None:
    observer = _OBSERVER.get()
    if observer is not None and trace is not None:
        observer(trace, max(0.0, elapsed_seconds))
