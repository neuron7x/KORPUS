"""Shared immutable SLO contract result type."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Predicate:
    id: str
    passed: bool
    evidence: str


def pred(identifier: str, passed: bool, evidence: str) -> Predicate:
    return Predicate(identifier, bool(passed), evidence)
