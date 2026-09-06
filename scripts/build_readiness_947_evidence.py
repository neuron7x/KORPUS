#!/usr/bin/env python3
"""Assemble machine-verifiable evidence for the 94.7 engineering-readiness profile.

The builder never converts missing evidence into PASS. It accepts package evidence only
through an explicit machine file produced after deterministic package verification.
External trust predicates are reported as gaps and are not included in the engineering
maturity numerator.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402


def _json(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _exit(name: str) -> bool:
    path = ROOT / f"var/readiness947/{name}.exit"
    return path.is_file() and path.read_text(encoding="utf-8").strip() == "0"


def _report_pass(
    relative: str, *, source_digest: str | None = None, release: str | None = None
) -> bool:
    value = _json(relative)
    passed = value.get("status") == "PASS" or value.get("valid") is True
    if not passed:
        return False
    if source_digest is not None and value.get("source_tree_sha256") != source_digest:
        return False
    return not (release is not None and value.get("release") != release)


def _junit(relative: str) -> dict[str, int]:
    path = ROOT / relative
    if not path.is_file():
        return {"tests": 0, "failures": 1, "errors": 0, "skipped": 0}
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    keys = ("tests", "failures", "errors", "skipped")
    return {key: sum(int(float(suite.attrib.get(key, "0"))) for suite in suites) for key in keys}


def _clean_source() -> bool:
    for path in ROOT.rglob("*"):
        if path.is_dir() and path.name in {"__pycache__", ".pytest_cache"}:
            return False
        if path.is_file() and path.suffix in {".pyc", ".pyo"}:
            return False
    return True


def _dataset_controls() -> int:
    path = ROOT / "evals/datasets/assurance.jsonl"
    count = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("expected_status") != "answered":
            count += 1
    return count


def _targeted_state(targeted: dict[str, Any]) -> dict[str, str]:
    """PASS / FAIL / NOT_MEASURED — три стани там, де стояв один булевий.

    `targeted_ok` злипав три різні світи в одне `False`: замало відібрано, справжні
    падіння, і «не бігало». Читач бачив хибне й висновував, що тести падають.

    ВИМІРЯНО 06.09.2026 на `723d9bb4`: 48 пропущених, з них **44 через ненастроєний
    PostgreSQL** (`test_postgres_rls_policy_state`, `..._approval_provenance`,
    `..._role_reprovision_boundary`, `..._rls_claim_forgery` і решта тим самим).
    Канонічний бекенд релізу — PostgreSQL (`production-v1.json`), а число готовності
    рахується з прогону на SQLite, який НЕ МОЖЕ дати нуль пропусків. Критерій не
    хибний і не недосяжний: його міряють там, де предмета нема.

    Різниця практична, і в неї різний адресат. `FAIL` знімає інженер, полагодивши
    тест. `NOT_MEASURED` знімає той, хто дає середовище: один прогін батареї під
    сконфігурованим постгресом переводить 44 пропуски у виконані.

    Поведінка споживача НЕ змінена: `targeted_ok` і далі істинний рівно на `PASS`.
    Виправлено те, що звіт КАЗАВ про свою відмову, а не те, що з неї випливає.
    """
    if targeted["tests"] < 60:
        return {"state": "NOT_MEASURED", "reason": f"відібрано {targeted['tests']} < 60"}
    if targeted["failures"] or targeted["errors"]:
        return {
            "state": "FAIL",
            "reason": f"падінь {targeted['failures']}, помилок {targeted['errors']}",
        }
    if targeted["skipped"]:
        return {
            "state": "NOT_MEASURED",
            "reason": (
                f"{targeted['skipped']} тестів пропущено: середовище прогону не має "
                "предмета (переважно ненастроєний PostgreSQL). Невиконане не є ні "
                "пройденим, ні проваленим"
            ),
        }
    return {"state": "PASS", "reason": "цільова регресія виконана повністю"}


def _package_evidence(path: Path | None) -> dict[str, bool]:
    if path is None or not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    checks = value.get("checks", {}) if isinstance(value, dict) else {}
    return (
        {str(key): bool(flag) for key, flag in checks.items()} if isinstance(checks, dict) else {}
    )


def _all_true(value: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return all(bool(value.get(key)) for key in keys)


def _migration_carry_ok(report: dict[str, Any], baseline_digest: str) -> bool:
    provenance = report.get("provenance", {})
    return (
        report.get("migration") == "head"
        and report.get("table_set_match") is True
        and report.get("column_failures") == {}
        and report.get("audit_head_seeded") is True
        and report.get("sqlite_fts5_present") is True
        and isinstance(provenance, dict)
        and provenance.get("source_digest") == baseline_digest
    )


def _load_phase_ok(phase: Any) -> bool:
    if not isinstance(phase, dict) or int(phase.get("requests", 0)) <= 0:
        return False
    statuses = phase.get("statuses", {})
    return (
        isinstance(statuses, dict)
        and sum(int(value) for value in statuses.values()) == int(phase["requests"])
        and all(str(code).startswith("2") for code in statuses)
    )


def _local_load_carry_ok(report: dict[str, Any], baseline_digest: str) -> bool:
    return (
        report.get("source_tree_sha256") == baseline_digest
        and report.get("release") == "v0.6.1"
        and report.get("environment_class") == "LOCAL_DEV"
        and all(_load_phase_ok(report.get(name)) for name in ("load", "spike", "soak"))
        and float(report.get("drift_p50_seconds", 1e9)) < 1.0
    )


def _context(package_evidence_path: Path | None) -> dict[str, Any]:
    source_digest = compute_source_digest(ROOT)
    release = release_tag()
    carry = _json(f"reports/release/{release}/REGRESSION_CARRY_FORWARD.json")
    targeted = _junit("var/readiness947/focused-current.xml")
    baseline_backend = _json("reports/release/v0.6.1/FULL_BACKEND_REPORT.json")
    coverage = _json("reports/release/v0.6.1/COVERAGE_REPORT.json")
    mutation = _json("reports/release/v0.6.1/MUTATION_PRODUCTION_GATE.json")
    carry_ok = (
        carry.get("status") == "PASS" and carry.get("target_source_tree_sha256") == source_digest
    )
    targeted_state = _targeted_state(targeted)
    targeted_ok = targeted_state["state"] == "PASS"
    return {
        "source_digest": source_digest,
        "release": release,
        "carry": carry,
        "carry_ok": carry_ok,
        "targeted": targeted,
        "targeted_state": targeted_state,
        "targeted_ok": targeted_ok,
        "baseline_backend": baseline_backend,
        "coverage": coverage,
        "mutation": mutation,
        "migration": _json("reports/release/v0.6.1/MIGRATION_GATE.json"),
        "local_load": _json("reports/release/v0.6.1/closeout/LOCAL_LIVE_LOAD_SOAK.json"),
        "auth": _json("reports/release/v0.6.1/AUTHORIZATION_INTERNAL_CURRENT.json"),
        "states": _json("reports/release/v0.6.1/STATE_CONTRACTS_CURRENT.json"),
        "observability": _json("reports/release/v0.6.1/OBSERVABILITY_CURRENT.json"),
        "eval_report": _json("var/eval-report.json"),
        "pkg": _package_evidence(package_evidence_path),
    }


def _derived(context: dict[str, Any]) -> dict[str, bool]:
    baseline_backend = context["baseline_backend"]
    coverage = context["coverage"]
    mutation = context["mutation"]
    eval_report = context["eval_report"]
    carry_ok = bool(context["carry_ok"])
    source_digest, release = context["source_digest"], context["release"]
    current = {"source_digest": source_digest, "release": release}
    return {
        "baseline_backend_ok": carry_ok
        and baseline_backend.get("status") == "PASS"
        and baseline_backend.get("failed") == 0
        and baseline_backend.get("errors") == 0,
        "coverage_ok": carry_ok and float(coverage.get("statement_coverage_percent", 0.0)) >= 95.0,
        "branch_ok": carry_ok and float(coverage.get("branch_coverage_percent", 0.0)) >= 90.0,
        "mutation_ok": carry_ok
        and mutation.get("status") == "PASS"
        and mutation.get("killed") == mutation.get("valid_mutants") == mutation.get("mutants"),
        "redteam_ok": _report_pass(
            f"reports/release/{release}/REDTEAM_INTERNAL_CURRENT.json", **current
        ),
        "reliability_ok": _report_pass(
            f"reports/release/{release}/RELIABILITY_INTERNAL_CURRENT.json", **current
        ),
        "builtin_ok": _report_pass(
            f"reports/release/{release}/BUILTIN_SECURITY_GATE.json", **current
        ),
        "model_check_ok": _report_pass(
            f"reports/release/{release}/ASSURANCE_MODEL_CHECK.json", **current
        ),
        "deterministic_ok": _report_pass(
            f"reports/release/{release}/DETERMINISM_GATE.json", **current
        ),
        "stress_ok": _report_pass(f"reports/release/{release}/STRESS_GATE.json", **current),
        "plasticity_ok": _report_pass(f"reports/release/{release}/PLASTICITY_GATE.json", **current),
        "eval_ok": bool(eval_report)
        and eval_report.get("passed") == eval_report.get("total")
        and eval_report.get("citation_failures") == 0
        and eval_report.get("leakage_failures") == 0
        and eval_report.get("determinism_failures") == 0,
        "web_ok": _exit("web_lint") and _exit("web_test") and _exit("web_build"),
        "source_manifest_ok": _exit("source_manifest"),
    }


def _product_core(context: dict[str, Any], flags: dict[str, bool]) -> dict[str, bool]:
    carry_ok, targeted_ok = bool(context["carry_ok"]), bool(context["targeted_ok"])
    return {
        "release_identity": _exit("release_identity"),
        "repository_validation": _exit("repository"),
        "openapi_contract": _exit("openapi"),
        "import_cycles": _exit("import_cycles"),
        "module_budget": _exit("module_budget"),
        "dependency_lock_structure": _exit("dependency_locks"),
        "state_contracts": carry_ok and context["states"].get("status") == "PASS",
        "authorization_matrix": carry_ok and context["auth"].get("status") == "PASS",
        "learning_graph": targeted_ok and carry_ok,
        "startup_failure_semantics": targeted_ok and carry_ok,
        "web_contract": flags["web_ok"] and _exit("openapi"),
        "source_digest_stable": carry_ok,
        "version_coherence": _exit("release_identity"),
    }


def _architecture(context: dict[str, Any], flags: dict[str, bool]) -> dict[str, bool]:
    carry_ok, targeted_ok = bool(context["carry_ok"]), bool(context["targeted_ok"])
    criteria = {
        name: carry_ok
        for name in (
            "identity_before_query",
            "authorization_before_retrieval",
            "retrieval_scope_noninterference",
            "claim_evidence_binding",
            "conflict_surface",
            "abstention",
            "provenance_binding",
            "privileged_action_boundary",
            "offline_integrity",
            "tamper_evident_audit",
        )
    }
    criteria.update(
        {
            "learning_graph_immutability": targeted_ok and carry_ok,
            "release_state_machine": targeted_ok,
            "bounded_model_check": flags["model_check_ok"],
            "evidence_conflict_preservation": targeted_ok,
            "inference_fixpoint_budget": targeted_ok,
        }
    )
    return criteria


def _security(context: dict[str, Any], flags: dict[str, bool]) -> dict[str, bool]:
    redteam_ok, builtin_ok, carry_ok = (
        flags["redteam_ok"],
        flags["builtin_ok"],
        bool(context["carry_ok"]),
    )
    criteria = {
        name: redteam_ok
        for name in (
            "indirect_prompt_injection",
            "egress_classification",
            "idor_refusal",
            "ssrf_egress",
            "webhook_replay",
            "host_header",
            "csrf_session",
            "upload_quarantine",
            "parser_bounds",
            "audit_integrity",
            "tenant_scope_application",
            "internal_redteam",
        )
    }
    criteria.update(
        {
            "builtin_security_gate": builtin_ok,
            "authorization_matrix": carry_ok and context["auth"].get("status") == "PASS",
            "secrets_static_heuristic": builtin_ok,
            "dangerous_primitive_scan": builtin_ok,
            "unknown_permission_fail_closed": carry_ok and context["auth"].get("status") == "PASS",
        }
    )
    return criteria


def _tests(context: dict[str, Any], flags: dict[str, bool]) -> dict[str, bool]:
    carry_ok, targeted_ok = bool(context["carry_ok"]), bool(context["targeted_ok"])
    return {
        "backend_regression_carry_forward": flags["baseline_backend_ok"],
        "targeted_current_source": targeted_ok,
        "statement_coverage": flags["coverage_ok"],
        "branch_coverage": flags["branch_ok"],
        "mutation_catalogue": flags["mutation_ok"],
        "determinism": flags["deterministic_ok"],
        "stress": flags["stress_ok"],
        "plasticity": flags["plasticity_ok"],
        "web_suite_current": flags["web_ok"],
        "evaluation_harness_contract": flags["eval_ok"],
        "synthetic_adversarial_eval": flags["eval_ok"],
        "null_controls": _dataset_controls() >= 10,
        "attack_family_coverage": flags["redteam_ok"],
        "migration_gate": carry_ok
        and _migration_carry_ok(
            context["migration"], str(context["carry"].get("baseline_source_tree_sha256", ""))
        ),
        "assurance_model_check": flags["model_check_ok"],
        "evidence_fusion_tests": targeted_ok,
        "inference_budget_tests": targeted_ok,
    }


def _package(context: dict[str, Any], flags: dict[str, bool]) -> dict[str, bool]:
    pkg = context["pkg"]
    return {
        "clean_source": _clean_source(),
        "source_manifest": flags["source_manifest_ok"],
        "distribution_manifest": pkg.get("distribution_manifest", False),
        "package_verifier": pkg.get("package_verifier", False),
        "reproducible_archive": pkg.get("reproducible_archive", False),
        "release_identity": _exit("release_identity"),
        "package_root_contract": pkg.get("package_root_contract", False),
        "file_mode_normalization": pkg.get("file_mode_normalization", False),
        "duplicate_path_rejection": pkg.get("duplicate_path_rejection", False),
        "zip_traversal_rejection": pkg.get("zip_traversal_rejection", False),
        "checksum": pkg.get("checksum", False),
        "claim_ledger": (
            ROOT / f"reports/release/{context['release']}/final/CLAIM_LEDGER.json"
        ).is_file(),
        "blocker_registry": (
            ROOT / f"reports/release/{context['release']}/final/BLOCKER_REGISTRY.json"
        ).is_file(),
        "portable_evidence_index": (
            ROOT / "reports/EXECUTABLE_EVIDENCE_INDEX_CURRENT.json"
        ).is_file(),
        "stale_current_rejection": _exit("current_truth"),
    }


def _reliability(context: dict[str, Any], flags: dict[str, bool]) -> dict[str, bool]:
    carry_ok = bool(context["carry_ok"])
    local_load = carry_ok and _local_load_carry_ok(
        context["local_load"], str(context["carry"].get("baseline_source_tree_sha256", ""))
    )
    return {
        "internal_fault_injection": flags["reliability_ok"],
        "chaos_matrix": _report_pass(
            f"reports/release/{context['release']}/CHAOS_MATRIX_CURRENT.json",
            source_digest=context["source_digest"],
            release=context["release"],
        ),
        "local_load": local_load,
        "local_spike": local_load,
        "local_soak": local_load,
        "local_recovery": carry_ok
        and _report_pass("reports/release/v0.6.1/SQLITE_RECOVERY_CURRENT.json"),
        "observability_contract": carry_ok and context["observability"].get("status") == "PASS",
        "slo_policy": flags["reliability_ok"],
        "retry_idempotency": flags["reliability_ok"],
        "bounded_audit_backlog": flags["reliability_ok"],
    }


def _ui(flags: dict[str, bool]) -> dict[str, bool]:
    return {
        "web_lint": _exit("web_lint"),
        "web_tests": _exit("web_test"),
        "web_build": _exit("web_build"),
        "contract_sync": _exit("openapi") and flags["web_ok"],
        "destruction_validation": flags["web_ok"],
    }


def _maintainability(context: dict[str, Any], flags: dict[str, bool]) -> dict[str, bool]:
    return {
        "module_budget": _exit("module_budget"),
        "dependency_locks": _exit("dependency_locks"),
        "standards_map": _exit("standards"),
        "documentation_truth": _exit("current_truth"),
        "source_inventory": flags["source_manifest_ok"],
        "deterministic_packaging": context["pkg"].get("reproducible_archive", False),
        "ruff_exact": _exit("ruff_exact"),
        "mypy_exact": _exit("mypy_exact"),
    }


def _dimension(
    *, criteria: dict[str, bool], evidence_class: str, source_digest: str, release: str
) -> dict[str, Any]:
    """Aggregate a readiness dimension without manufacturing a green status.

    A dimension is PASS only when every declared criterion is satisfied. Empty
    criterion maps are rejected as FAIL because they carry no executable evidence.
    """

    complete = bool(criteria) and all(criteria.values())
    return {
        "status": "PASS" if complete else "FAIL",
        "source_tree_sha256": source_digest,
        "release": release,
        "evidence_class": evidence_class,
        "criteria": criteria,
        "failures": sorted(name for name, ok in criteria.items() if not ok),
    }


def build(package_evidence_path: Path | None = None) -> dict[str, Any]:
    context = _context(package_evidence_path)
    flags = _derived(context)
    common = {"source_digest": context["source_digest"], "release": context["release"]}
    dimensions = {
        "product_core": _dimension(
            criteria=_product_core(context, flags),
            evidence_class="EXECUTED_WITH_NEGATIVE_CONTROL",
            **common,
        ),
        "architecture_invariants": _dimension(
            criteria=_architecture(context, flags),
            evidence_class="EXECUTED_WITH_NEGATIVE_CONTROL",
            **common,
        ),
        "security_internal": _dimension(
            criteria=_security(context, flags),
            evidence_class="EXECUTED_WITH_NEGATIVE_CONTROL",
            **common,
        ),
        "tests_tevv": _dimension(
            criteria=_tests(context, flags),
            evidence_class="EXECUTED_WITH_NEGATIVE_CONTROL",
            **common,
        ),
        "release_package_integrity": _dimension(
            criteria=_package(context, flags),
            evidence_class="EXECUTED_WITH_NEGATIVE_CONTROL",
            **common,
        ),
        "reliability_internal": _dimension(
            criteria=_reliability(context, flags),
            evidence_class="EXECUTED_WITH_NEGATIVE_CONTROL",
            **common,
        ),
        "ui_ux": _dimension(
            criteria=_ui(flags), evidence_class="EXECUTED_WITH_NEGATIVE_CONTROL", **common
        ),
        "maintainability_reproducibility": _dimension(
            criteria=_maintainability(context, flags), evidence_class="EXECUTED", **common
        ),
    }
    return {
        "schema": "korpus.engineering-readiness-evidence.v1",
        "profile_id": "engineering-technical-academic-readiness-94.7",
        "source_tree_sha256": context["source_digest"],
        "release": context["release"],
        "dimensions": dimensions,
        "raw_evidence": {
            "targeted_junit": context["targeted"],
            "carry_forward": context["carry"].get("checks", {}),
            "baseline_backend": {
                key: context["baseline_backend"].get(key)
                for key in ("collected", "passed", "failed", "errors", "skipped")
            },
            "coverage": {
                key: context["coverage"].get(key)
                for key in (
                    "statement_coverage_percent",
                    "branch_coverage_percent",
                    "missing_branches",
                )
            },
            "mutation": {
                key: context["mutation"].get(key) for key in ("mutants", "valid_mutants", "killed")
            },
            "synthetic_null_controls": _dataset_controls(),
            "package_checks": context["pkg"],
        },
        "external_noncompensable": [
            "external_independent_redteam",
            "live_vulnerability_scanners",
            "live_postgres_rls",
            "real_domain_corpus_tevv",
            "independent_tevv",
            "production_like_tevv_environment",
            "production_like_load",
            "trusted_load_attestation",
            "trusted_recovery_attestation",
            "trusted_hosted_builder",
            "trusted_release_signing",
            "exact_python_3_12_13_environment",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-evidence", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    package_path = args.package_evidence.resolve() if args.package_evidence else None
    payload = build(package_path)
    default_out = (
        ROOT / f"reports/release/{payload['release']}/ENGINEERING_READINESS_94_7_EVIDENCE.json"
    )
    out = (
        default_out
        if args.out is None
        else (args.out if args.out.is_absolute() else ROOT / args.out)
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
