from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

OWNER_METADATA_SCHEMA = "korpus.owner-packet-metadata.v1"
OWNER_METADATA_STATUS = "CURRENT"
OWNER_METADATA_PREFIX = "KORPUS_OWNER_PACKET_METADATA"


def owner_metadata_line(release: str, digest: str) -> str:
    """Канонічний машиночитний конверт пакета."""
    payload = {
        "schema": OWNER_METADATA_SCHEMA,
        "status": OWNER_METADATA_STATUS,
        "release": release,
        "source_tree_sha256": digest,
        "digest_scope": "evidence_paths",
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"<!-- {OWNER_METADATA_PREFIX} {encoded} -->"


#: Поверхня, яку міряє `compute_source_digest`. Друга поверхня — `tracked_tree` зі
#: `scripts/source_digest.py` — інша, і її автор написав це першим абзацом докстрінга:
#: «Both were written into a field named `source_tree_sha256`, so a report signed by one
#: and verified against the other fails as "unbound" — a message about the tree changing,
#: when the tree did not change and two different scopes were compared. Carry
#: `digest_scope` beside the value and compare scopes before hashes.»
#:
#: ВИМІРЯНО 05.09.2026: із 200 артефактів із полем `source_tree_sha256` поле `digest_scope`
#: несе РІВНО ОДИН. Тобто припис лежав у коді й не був виконаний, а читач порівнював
#: числа, не спитавши, чи вони про одну поверхню. Тут виконано для п'яти артефактів,
#: які цей контракт справді ЧИТАЄ; історичні релізи не переписуються — заморожений доказ
#: не сміє змінюватись заднім числом, і UNKNOWN для них лишається UNKNOWN.
EVIDENCE_SCOPE = "evidence_paths"


def scope_agrees(payload: dict[str, Any], expected: str = EVIDENCE_SCOPE) -> bool:
    """Чи артефакт НАЗИВАЄ ту саму поверхню. Не назвав — не довів."""
    return payload.get("digest_scope") == expected


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _passing_report(payload: dict[str, Any]) -> bool:
    return payload.get("status") == "PASS" and payload.get("failures") == []


def _executable_index(payload: dict[str, Any]) -> bool:
    counts = (
        payload.get("source_python_modules"),
        payload.get("test_python_modules"),
        payload.get("test_functions_static"),
        payload.get("test_file_prefix_modules"),
    )
    return (
        all(type(value) is int and value >= 0 for value in counts)
        and payload.get("method") == "AST enumeration over current source/test tree"
        and "status" not in payload
    )


CURRENT_REPORT_CONTRACTS: dict[str, tuple[str, Callable[[dict[str, Any]], bool]]] = {
    "reports/DEPENDENCY_LOCK_VERIFICATION_CURRENT.json": (
        "korpus.dependency-lock-verification.v2",
        _passing_report,
    ),
    "reports/STANDARDS_CONTROL_MAP_VERIFICATION.json": (
        "korpus.standards-control-map-verification.v2",
        _passing_report,
    ),
    "reports/EXECUTABLE_EVIDENCE_INDEX_CURRENT.json": (
        "korpus.executable-evidence-index.v2",
        _executable_index,
    ),
}
CURRENT_REPORTS = tuple(CURRENT_REPORT_CONTRACTS)


def report_binding_checks(root: Path, release: str, digest: str) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for relative, (schema, semantic_check) in CURRENT_REPORT_CONTRACTS.items():
        path = root / relative
        checks[f"{relative}.present"] = path.is_file()
        if not path.is_file():
            continue
        try:
            payload = load_object(path)
        except (OSError, json.JSONDecodeError, ValueError):
            checks[f"{relative}.object_valid"] = False
            continue
        checks[f"{relative}.object_valid"] = True
        checks[f"{relative}.schema_exact"] = payload.get("schema") == schema
        checks[f"{relative}.contract_valid"] = semantic_check(payload)
        bound_digest = payload.get("source_tree_sha256", payload.get("source_digest"))
        agrees = scope_agrees(payload)
        checks[f"{relative}.scope_named"] = agrees
        checks[f"{relative}.source_bound"] = agrees and bound_digest == digest
        checks[f"{relative}.release_bound"] = payload.get("release") == release
    return checks


def final_truth_checks(root: Path, release: str, digest: str) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for name in ("BLOCKER_REGISTRY.json", "CLAIM_LEDGER.json"):
        path = root / f"reports/release/{release}/final/{name}"
        checks[f"{name}.present"] = path.is_file()
        if path.is_file():
            payload = load_object(path)
            agrees = scope_agrees(payload)
            checks[f"{name}.scope_named"] = agrees
            checks[f"{name}.source_bound"] = agrees and payload.get("source_tree_sha256") == digest
            checks[f"{name}.release_bound"] = payload.get("release") == release
    return checks
