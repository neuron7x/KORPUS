#!/usr/bin/env python3
"""Execute every locally callable external gate and emit a 24-gate causal scorecard."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]
from korpus.application.production_hard_predicates import (  # noqa: E402
    evaluate_hard_predicates,
    load_hard_predicate_profile,
)
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402

PROFILE = "config/assurance/production-hard-predicates-v1.json"
GATE_FILES = {
    "redteam": "redteam-gate.json",
    "supply_chain": "supply_chain-gate.json",
    "postgres_security": "postgres_security-gate.json",
    "tevv": "tevv-gate.json",
    "reliability": "reliability-gate.json",
    "exact_environment": "exact_environment-gate.json",
    "final_release": "final_release-gate.json",
}
RUNNERS = {
    "redteam": "scripts/validate_external_redteam_evidence.py",
    "supply_chain": "scripts/run_supply_chain_gate.py",
    "postgres_security": "scripts/run_postgres_security_gate.py",
    "tevv": "scripts/run_tevv_production_gate.py",
    "reliability": "scripts/run_reliability_gate.py",
    "exact_environment": "scripts/run_exact_environment_gate.py",
}


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _execute(root: Path) -> dict[str, dict[str, Any]]:
    executions: dict[str, dict[str, Any]] = {}
    for gate, relative in RUNNERS.items():
        completed = subprocess.run(
            [sys.executable, relative],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=900,
            env={**os.environ, "PYTHONPATH": str(root / "apps/api/src")},
        )
        executions[gate] = {
            "exit_code": completed.returncode,
            "stdout_tail": completed.stdout[-2000:],
            "stderr_tail": completed.stderr[-2000:],
        }
    return executions


def _capabilities() -> dict[str, Any]:
    tools = {
        name: shutil.which(name)
        for name in (
            "docker",
            "podman",
            "psql",
            "postgres",
            "trivy",
            "gitleaks",
            "grype",
            "syft",
            "terraform",
            "cosign",
        )
    }
    return {
        "python": platform.python_version(),
        "tools": tools,
        "test_database_url": bool(os.getenv("KORPUS_TEST_DATABASE_URL")),
        "trusted_builder_id": bool(os.getenv("KORPUS_TRUSTED_BUILDER_ID")),
    }


def _cause(
    predicate_id: str,
    externally_satisfied: bool,
    gate: dict[str, Any],
    capabilities: dict[str, Any],
) -> str:
    if externally_satisfied:
        return "PASS"
    tools = capabilities["tools"]
    if predicate_id == "live_postgres_rls" and not (
        capabilities["test_database_url"] or tools["docker"] or tools["podman"]
    ):
        return "RUNTIME_UNAVAILABLE"
    if predicate_id == "live_vulnerability_scanners" and not any(
        tools[name] for name in ("trivy", "gitleaks", "grype")
    ):
        return "TOOL_UNAVAILABLE"
    if predicate_id == "exact_python_3_12_13_environment" and capabilities["python"] != "3.12.13":
        return "RUNTIME_UNAVAILABLE"
    if predicate_id in {"external_independent_redteam", "independent_tevv"}:
        return "INDEPENDENCE_REQUIRED"
    if predicate_id in {
        "trusted_load_attestation",
        "trusted_recovery_attestation",
        "trusted_release_signing",
    }:
        return "TRUST_ROOT_OR_ATTESTATION_MISSING"
    if predicate_id == "trusted_hosted_builder":
        return "HOSTED_BUILDER_REQUIRED"
    if predicate_id in {
        "real_domain_corpus_tevv",
        "production_like_tevv_environment",
        "production_like_load",
    }:
        return "EXTERNAL_INPUT_MISSING"
    return "EXECUTED_FAIL" if gate else "EVIDENCE_MISSING"


def build(root: Path, *, execute: bool) -> dict[str, Any]:
    root = root.resolve()
    executions = _execute(root) if execute else {}
    gate_dir = root / "var/production"
    gates = {name: _object(gate_dir / filename) for name, filename in GATE_FILES.items()}
    profile = load_hard_predicate_profile(root / PROFILE)
    source_digest = compute_source_digest(root)
    release = release_tag(root)
    states = evaluate_hard_predicates(
        root, profile, gates, current_source_sha256=source_digest, current_release=release
    )
    capabilities = _capabilities()
    external = []
    for state in states:
        external.append(
            {
                **state.as_dict(),
                "causal_status": _cause(
                    state.predicate_id,
                    state.externally_satisfied,
                    gates.get(state.gate, {}),
                    capabilities,
                ),
            }
        )
    software_pass = sum(state.software_ready for state in states)
    external_pass = sum(state.externally_satisfied for state in states)
    completed, total = software_pass + external_pass, len(states) * 2
    return {
        "schema": "korpus.production-24-gate-campaign.v1",
        "release": release,
        "source_tree_sha256": source_digest,
        "status": "PASS" if completed == total else "FAIL_CLOSED",
        "software_gates": {"passed": software_pass, "total": len(states)},
        "external_gates": {"passed": external_pass, "total": len(states)},
        "combined": {
            "passed": completed,
            "total": total,
            "percent": round(100.0 * completed / total, 6),
        },
        "capabilities": capabilities,
        "executions": executions,
        "predicates": external,
        "production_authorized": completed == total,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--no-execute", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    payload = build(root, execute=not args.no_execute)
    out = args.out or (
        root / f"reports/release/{payload['release']}/PRODUCTION_24_GATE_SCORECARD.json"
    )
    out = out if out.is_absolute() else root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["production_authorized"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
