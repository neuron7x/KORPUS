from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from korpus.application.release_claims import claim_ledger as claim_ledger


def inventory(root: Path) -> dict[str, int]:
    source_files = sorted((root / "apps/api/src").rglob("*.py"))
    test_files = sorted((root / "apps/api/tests").glob("*.py"))
    tests = sum(
        sum(
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name.startswith("test_")
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        )
        for path in test_files
    )
    return {
        "source_python_modules": len(source_files),
        "test_python_modules": len(test_files),
        "test_functions_static": tests,
        "test_file_prefix_modules": sum(path.name.startswith("test_") for path in test_files),
    }


def _hard_state(
    report: dict[str, Any], source_digest: str, release: str
) -> tuple[bool, dict[str, dict[str, Any]]]:
    current = report.get("source_tree_sha256") == source_digest and report.get("release") == release
    states = {
        str(item.get("id")): item
        for item in report.get("states", ())
        if current and isinstance(item, dict)
    }
    return current, states


def _evidence_digest(path: Path) -> str:
    """Дайджест ЗМІСТУ доказу, з якого зібрано реєстр.

    `source_tree_sha256` не покриває `reports/` — і не має покривати, інакше доказ
    знецінював би сам себе щоразу, як його переписують. Але наслідок цього виключення
    той, що реєстр залишається «прив'язаним» до дерева, коли ЗМІНИВСЯ його вхід.

    Виміряно 04.09.2026 на кандидаті f311e83a: `BLOCKER_REGISTRY.json` зібрано о 13:20,
    `PRODUCTION_HARD_PREDICATES.json` перезібрано о 19:50 і закомічено в ТОМУ САМОМУ
    коміті. Перегенерація реєстру на незміненому дереві перевела 7 блокерів
    EXTERNAL_REQUIRED → CLOSED_ANCHORED і одну претензію STALE_EVIDENCE → SUPPORTED.
    Жоден гейт цього не бачив: допуск звіряв `source_tree_sha256`, і той збігався —
    прив'язка трималась, а зміст розійшовся.

    `evidence_current` теж не рятує: воно каже, що ДОКАЗ прив'язаний до того ж дерева,
    а не що реєстр зібрано саме з ЦЬОГО доказу. Тому тут — дайджест змісту.
    """
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _blocker_item(
    raw: Mapping[str, Any], state: Mapping[str, Any], current: bool
) -> dict[str, Any]:
    """Один блокер: готовність коду і зовнішня вдоволеність — РІЗНІ осі, не одна."""
    software = state.get("software_ready") is True
    external = state.get("externally_satisfied") is True
    status = (
        "CLOSED_ANCHORED"
        if software and external
        else "EXTERNAL_REQUIRED"
        if software
        else "INTERNAL_BLOCKED"
    )
    return {
        "id": str(raw["id"]),
        "state": status,
        "evidence": "reports/PRODUCTION_HARD_PREDICATES.json",
        "evidence_current": current,
        "software_ready": software,
        "externally_satisfied": external,
        "required_proof_class": raw.get("required_proof_class"),
    }


def blocker_registry(root: Path, source_digest: str, release: str) -> dict[str, Any]:
    profile = json.loads(
        (root / "config/assurance/production-hard-predicates-v1.json").read_text(encoding="utf-8")
    )
    report_path = root / "reports/PRODUCTION_HARD_PREDICATES.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    current, states = _hard_state(report, source_digest, release)
    items = [
        _blocker_item(raw, states.get(str(raw["id"]), {}), current)
        for raw in profile.get("predicates", ())
    ]
    counts = {
        state: sum(item["state"] == state for item in items)
        for state in {item["state"] for item in items}
    }
    return {
        "schema": "korpus.blocker-registry.v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "release": release,
        "source_tree_sha256": source_digest,
        "items": items,
        "counts": counts,
        "internal_executable_unresolved": counts.get("INTERNAL_BLOCKED", 0),
        "production_external_or_runtime_unresolved": counts.get("EXTERNAL_REQUIRED", 0),
        "hard_predicates_total": len(profile.get("predicates", ())),
        "hard_predicate_report_current": current,
        "evidence_sha256": {
            "reports/PRODUCTION_HARD_PREDICATES.json": _evidence_digest(report_path)
        },
    }


def status_ontology() -> dict[str, Any]:
    return {
        "schema": "korpus.status-ontology.v2",
        "states": {
            "CLOSED_ANCHORED": "Executed or byte-verified and supported by source-bound evidence.",
            "CARRY_FORWARD_SOURCE_BOUND": "Historical execution is admissible only after byte-level proof over unchanged governed runtime paths.",
            "RUNTIME_UNAVAILABLE": "Required tool/runtime is unavailable; this is neither PASS nor code failure.",
            "INTERNAL_BLOCKED": "Repository-side executable or admission precondition is missing.",
            "EXTERNAL_REQUIRED": "Predicate requires independent authority, production-like infrastructure, or pre-admitted trust root.",
            "CONFLICT": "Compatible evidence contradicts; conflict remains explicit and fails closed.",
            "FAIL": "Executed predicate failed.",
            "UNKNOWN": "Insufficient evidence.",
        },
        "promotion_rule": "Readiness is weighted and non-authorizing; production authorization is conjunctive and cannot be compensated by score.",
    }
