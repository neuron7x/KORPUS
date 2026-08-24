from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from korpus.application.admission import evaluate_admission, load_register
from korpus.application.provenance import verify_reports
from korpus.application.numeric_contracts import finite_number
from korpus.application.operational_math import evaluate_operational_checks


def jensen_shannon_divergence(left: Sequence[float], right: Sequence[float]) -> float:
    """Symmetric bounded distribution drift in bits, with explicit normalization."""

    if len(left) != len(right) or not left:
        raise ValueError("drift distributions must be non-empty and equal length")
    if any(not finite_number(value) or float(value) < 0 for value in (*left, *right)):
        raise ValueError("drift distributions must contain finite non-negative values")
    left_total = sum(left)
    right_total = sum(right)
    if left_total <= 0 or right_total <= 0:
        raise ValueError("drift distributions must have positive mass")
    p = [value / left_total for value in left]
    q = [value / right_total for value in right]
    # len(left) == len(right) is enforced above, so p, q and midpoint all have the
    # same length and strict=True can never fire on either zip.
    midpoint = [(a + b) / 2 for a, b in zip(p, q, strict=True)]

    def kl(source: Sequence[float], target: Sequence[float]) -> float:
        return sum(
            value * math.log2(value / comparison)
            for value, comparison in zip(source, target, strict=True)
            if value > 0
        )

    return 0.5 * kl(p, midpoint) + 0.5 * kl(q, midpoint)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class GateResult:
    status: str
    checks: Mapping[str, bool]
    failures: tuple[str, ...]
    evidence_sha256: Mapping[str, str]
    production_authorized: bool = False
    admission: Mapping[str, Any] | None = None

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": self.status,
            "production_authorized": self.production_authorized,
            "admission": dict(self.admission) if self.admission is not None else None,
            "checks": dict(self.checks),
            "failures": list(self.failures),
            "evidence_sha256": dict(self.evidence_sha256),
            "interpretation": (
                "Engineering release predicates passed; this is not corpus, security, "
                "regulatory, operational-SLA or military authorization."
            ),
        }


class OperationalReleaseGate:
    """Fail-closed evaluator over independently generated assurance artifacts."""

    REQUIRED_REPORTS = ("eval", "mutation", "migration", "scale")

    def __init__(
        self,
        policy: Mapping[str, Any],
        admission_register: Mapping[str, Any] | None = None,
        root: Path | None = None,
    ) -> None:
        if policy.get("schema_version") != 1:
            raise ValueError("unsupported operational policy schema")
        self.policy = policy
        # `production_authorized` used to be the literal False in the result. The answer
        # was right and unfalsifiable: nothing said what would have to be true instead,
        # and nobody could tell "still withheld" from "nobody looked". It is now computed
        # from the register of grounds, which states for each one who owns the evidence
        # and what class it must be. Absent a register the verdict stays false — a gate
        # that cannot see the grounds does not get to authorize anything.
        self.admission_register = admission_register
        self.root = root or Path.cwd()

    @classmethod
    def load(
        cls, path: Path, admission_path: Path | None = None, root: Path | None = None
    ) -> OperationalReleaseGate:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("operational policy must be an object")
        register = (
            load_register(admission_path)
            if admission_path is not None and admission_path.is_file()
            else None
        )
        return cls(value, register, root)

    def evaluate(
        self,
        reports: Mapping[str, Mapping[str, Any]],
        evidence_paths: Mapping[str, Path] | None = None,
        source_digest: str | None = None,
    ) -> GateResult:
        missing = [name for name in self.REQUIRED_REPORTS if name not in reports]
        if missing:
            return GateResult(
                status="FAIL",
                checks={"reports_present": False},
                failures=(f"missing reports: {', '.join(missing)}",),
                evidence_sha256={},
            )

        evaluation = reports["eval"]
        mutation = reports["mutation"]
        migration = reports["migration"]
        scale = reports["scale"]
        eval_policy = self.policy["evaluation"]
        mutation_policy = self.policy["mutation"]
        migration_policy = self.policy["migration"]
        scale_policy = self.policy["scale_probe"]

        # A report is evidence about a tree, not about the world: unless it was
        # produced by the tree being gated, its numbers describe something else.
        # No digest supplied means the binding cannot be checked, which fails
        # closed rather than degrading to "assume it matches".
        provenance_ok, provenance_reasons = (
            verify_reports({name: reports[name] for name in self.REQUIRED_REPORTS}, source_digest)
            if source_digest is not None
            else (False, ("source digest was not supplied to the gate",))
        )

        checks = {
            "reports_present": True,
            "evidence_provenance": provenance_ok,
            **evaluate_operational_checks(
                evaluation, mutation, migration, scale,
                eval_policy, mutation_policy, migration_policy, scale_policy,
            ),
        }
        failures = tuple(name for name, passed in checks.items() if not passed) + provenance_reasons
        evidence_hashes = {
            name: sha256_file(path)
            for name, path in (evidence_paths or {}).items()
            if path.is_file()
        }
        admission = (
            evaluate_admission(self.root, self.admission_register)
            if self.admission_register is not None
            else None
        )
        return GateResult(
            status="PASS" if not failures else "FAIL",
            checks=checks,
            failures=failures,
            evidence_sha256=evidence_hashes,
            # Engineering predicates passing is a precondition, never the authorization:
            # the grounds that withhold this system are not engineering grounds.
            production_authorized=bool(
                not failures and admission is not None and admission.production_authorized
            ),
            admission=admission.as_dict() if admission is not None else None,
        )
