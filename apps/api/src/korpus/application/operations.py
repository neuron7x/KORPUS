from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from korpus.application.provenance import verify_reports


def jensen_shannon_divergence(left: Sequence[float], right: Sequence[float]) -> float:
    """Symmetric bounded distribution drift in bits, with explicit normalization."""

    if len(left) != len(right) or not left:
        raise ValueError("drift distributions must be non-empty and equal length")
    if any(value < 0 or not math.isfinite(value) for value in (*left, *right)):
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

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": self.status,
            "production_authorized": self.production_authorized,
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

    def __init__(self, policy: Mapping[str, Any]) -> None:
        if int(policy.get("schema_version", 0)) != 1:
            raise ValueError("unsupported operational policy schema")
        self.policy = policy

    @classmethod
    def load(cls, path: Path) -> OperationalReleaseGate:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("operational policy must be an object")
        return cls(value)

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
        required_tables = set(migration_policy["required_tables"])
        actual_tables = set(migration.get("tables_actual", []))

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
            "eval_pass_rate": float(evaluation.get("pass_rate", -1))
            >= float(eval_policy["minimum_pass_rate"]),
            "citation_integrity": int(evaluation.get("citation_failures", -1))
            <= int(eval_policy["maximum_citation_failures"]),
            "access_noninterference": int(evaluation.get("leakage_failures", -1))
            <= int(eval_policy["maximum_leakage_failures"]),
            "determinism": int(evaluation.get("determinism_failures", -1))
            <= int(eval_policy["maximum_determinism_failures"]),
            "audit_chain": bool(evaluation.get("audit_valid"))
            is bool(eval_policy["require_audit_valid"]),
            "critical_mutation_score": float(mutation.get("mutation_score", -1))
            >= float(mutation_policy["minimum_critical_mutation_score"]),
            "critical_mutation_survivors": len(mutation.get("survived", ["UNKNOWN"]))
            <= int(mutation_policy["maximum_survivors"]),
            "migration_table_parity": bool(migration.get("table_set_match"))
            is bool(migration_policy["require_table_set_match"]),
            "migration_required_tables": required_tables.issubset(actual_tables),
            "migration_audit_head": bool(migration.get("audit_head_seeded"))
            is bool(migration_policy["require_audit_head"]),
            "migration_fts5": bool(migration.get("sqlite_fts5_present"))
            is bool(migration_policy["require_sqlite_fts5"]),
            "scale_status": scale.get("status") == "PASS",
            "scale_metric_provenance": scale.get("metric_status") == scale_policy["metric_status"],
            "scale_top1": float(scale.get("results", {}).get("top1_recall", -1))
            >= float(scale_policy["minimum_top1_recall"]),
            "scale_candidate_bound": int(scale.get("results", {}).get("candidate_count", 10**9))
            <= int(scale_policy["maximum_candidate_count"]),
            "scale_local_p95": float(
                scale.get("results", {}).get("query_latency_ms_p95", math.inf)
            )
            <= float(scale_policy["maximum_local_p95_ms"]),
        }
        failures = tuple(name for name, passed in checks.items() if not passed) + provenance_reasons
        evidence_hashes = {
            name: sha256_file(path)
            for name, path in (evidence_paths or {}).items()
            if path.is_file()
        }
        return GateResult(
            status="PASS" if not failures else "FAIL",
            checks=checks,
            failures=failures,
            evidence_sha256=evidence_hashes,
            production_authorized=False,
        )
