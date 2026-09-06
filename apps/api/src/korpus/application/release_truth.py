from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from korpus.application.provenance import DIGEST_SCOPE
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


#: Перевірки, які кажуть «артефакт не про ЦЕ дерево», а не «бракує зовнішньої сторони».
#: Прив'язка закривається ПЕРЕЗНЯТТЯМ гейта на цьому коміті — це машинна робота, і
#: називати її зовнішньою дією означає обіцяти, що людина зробить те, що зробить лан.
EVIDENCE_BINDING_CHECKS = frozenset(
    {
        "gate_source_bound",
        "gate_release_bound",
        "evidence_manifest_bound",
        "source_bound",
        "release_bound",
    }
)


def _machine_closable(state: dict[str, Any]) -> bool:
    """Чи вся прогалина предиката — застаріла прив'язка доказу.

    Виміряно 04.09.2026 на кандидаті d2964c6e: з дев'яти блокуючих предикатів п'ять
    падали ВИКЛЮЧНО на `gate_source_bound`, тобто на артефактах, знятих попереднього
    дня. Стара класифікація віддавала їх у EXTERNAL_REQUIRED, і
    `internal_executable_unresolved` читалось як нуль — при п'яти машинних блокерах.
    Число гейтує реліз через `current-truth`, тож критерій був слабший за властивість,
    яку називає.
    """
    failed = {str(item) for item in state.get("failed_external_checks") or ()}
    return bool(failed) and failed <= EVIDENCE_BINDING_CHECKS


def _blocker_state(state: dict[str, Any]) -> str:
    """Один із чотирьох станів. «Внутрішній» означає «машина може закрити», не «бракує файла»."""
    software = state.get("software_ready") is True
    if not software:
        return "INTERNAL_BLOCKED"
    if state.get("externally_satisfied") is True:
        return "CLOSED_ANCHORED"
    return "INTERNAL_STALE_EVIDENCE" if _machine_closable(state) else "EXTERNAL_REQUIRED"


def _blocker_item(
    predicate_id: str, raw: Mapping[str, Any], state: dict[str, Any], current: bool
) -> dict[str, Any]:
    """Один запис реєстру блокерів разом із підставою вироку."""
    software = state.get("software_ready") is True
    return {
        "id": predicate_id,
        "state": _blocker_state(state),
        "evidence": "reports/PRODUCTION_HARD_PREDICATES.json",
        "evidence_current": current,
        "software_ready": software,
        "externally_satisfied": state.get("externally_satisfied") is True,
        "machine_closable": software and _machine_closable(state),
        "failed_external_checks": sorted(
            str(item) for item in state.get("failed_external_checks") or ()
        ),
        "required_proof_class": raw.get("required_proof_class"),
    }


def evidence_digest(path: Path) -> str:
    """Дайджест ЗМІСТУ доказу, з якого зібрано реєстр.

    `source_tree_sha256` не покриває `reports/` і не має покривати — інакше доказ
    знецінював би себе щоразу, як його переписують. Ціна виключення: реєстр лишається
    «прив'язаним», коли змінився його ВХІД. Виміряно 04.09.2026 на f311e83a — реєстр і
    його доказ зібрані в тому самому коміті з різницею шість годин, і перезбирання на
    НЕЗМІНЕНОМУ дереві перевело 7 блокерів у CLOSED_ANCHORED непоміченим.

    Відсутній файл дає порожній рядок навмисно: споживач мусить прочитати це як
    «не виміряно», а не як збіг.
    """
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blocker_registry(root: Path, source_digest: str, release: str) -> dict[str, Any]:
    profile = json.loads(
        (root / "config/assurance/production-hard-predicates-v1.json").read_text(encoding="utf-8")
    )
    report_path = root / "reports/PRODUCTION_HARD_PREDICATES.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    current, states = _hard_state(report, source_digest, release)
    items: list[dict[str, Any]] = []
    for raw in profile.get("predicates", ()):
        predicate_id = str(raw["id"])
        state = states.get(predicate_id, {})
        items.append(_blocker_item(predicate_id, raw, state, current))
    counts = {
        state: sum(item["state"] == state for item in items)
        for state in {item["state"] for item in items}
    }
    # Обидва внутрішні стани рахуються разом: «бракує файла» і «доказ не про це дерево»
    # однаково закриваються машиною, і саме це стверджує назва поля.
    internal = counts.get("INTERNAL_BLOCKED", 0) + counts.get("INTERNAL_STALE_EVIDENCE", 0)
    external = counts.get("EXTERNAL_REQUIRED", 0)
    return {
        "schema": "korpus.blocker-registry.v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "release": release,
        "status": "PASS" if current and not internal and not external else "FAIL",
        "source_tree_sha256": source_digest,
        "digest_scope": DIGEST_SCOPE,
        "items": items,
        "counts": counts,
        "internal_executable_unresolved": internal,
        "internal_missing_artifact": counts.get("INTERNAL_BLOCKED", 0),
        "internal_stale_evidence": counts.get("INTERNAL_STALE_EVIDENCE", 0),
        "production_external_or_runtime_unresolved": external,
        "hard_predicates_total": len(profile.get("predicates", ())),
        "hard_predicate_report_current": current,
        "evidence_sha256": {
            "reports/PRODUCTION_HARD_PREDICATES.json": evidence_digest(report_path)
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
            "INTERNAL_STALE_EVIDENCE": "Gate evidence exists but is bound to another tree or release; closing it is a re-run, not an external action.",
            "EXTERNAL_REQUIRED": "Predicate requires independent authority, production-like infrastructure, or pre-admitted trust root.",
            "CONFLICT": "Compatible evidence contradicts; conflict remains explicit and fails closed.",
            "FAIL": "Executed predicate failed.",
            "UNKNOWN": "Insufficient evidence.",
        },
        "promotion_rule": "Readiness is weighted and non-authorizing; production authorization is conjunctive and cannot be compensated by score.",
    }
