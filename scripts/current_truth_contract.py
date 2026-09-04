from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CURRENT_REPORTS = (
    "reports/DEPENDENCY_LOCK_VERIFICATION_CURRENT.json",
    "reports/STANDARDS_CONTROL_MAP_VERIFICATION.json",
    "reports/EXECUTABLE_EVIDENCE_INDEX_CURRENT.json",
)

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


def report_binding_checks(root: Path, release: str, digest: str) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for relative in CURRENT_REPORTS:
        path = root / relative
        checks[f"{relative}.present"] = path.is_file()
        if not path.is_file():
            continue
        payload = load_object(path)
        bound_digest = payload.get("source_tree_sha256", payload.get("source_digest"))
        agrees = scope_agrees(payload)
        checks[f"{relative}.scope_named"] = agrees
        checks[f"{relative}.source_bound"] = agrees and bound_digest == digest
        if "release" in payload:
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


def alias_checks(root: Path, release: str) -> dict[str, bool]:
    envelope = root / "RELEASE_ENVELOPE.json"
    root_report = root / "CANONICAL_RELEASE_REPORT.json"
    report_alias = root / "reports/CANONICAL_RELEASE_REPORT.json"
    receipt = root / "FULL_SSOT_PACKAGE_RECEIPT.json"
    checks = {
        "RELEASE_ENVELOPE.present": envelope.is_file(),
        "CANONICAL_RELEASE_REPORT.root_present": root_report.is_file(),
        "CANONICAL_RELEASE_REPORT.alias_present": report_alias.is_file(),
        "FULL_SSOT_PACKAGE_RECEIPT.present": receipt.is_file(),
    }
    if envelope.is_file():
        checks["RELEASE_ENVELOPE.release_bound"] = load_object(envelope).get("release") == release
    if root_report.is_file():
        checks["CANONICAL_RELEASE_REPORT.root_release_bound"] = (
            load_object(root_report).get("release") == release
        )
    if report_alias.is_file():
        checks["CANONICAL_RELEASE_REPORT.alias_release_bound"] = (
            load_object(report_alias).get("release") == release
        )
    if root_report.is_file() and report_alias.is_file():
        checks["CANONICAL_RELEASE_REPORT.alias_exact"] = (
            root_report.read_bytes() == report_alias.read_bytes()
        )
    if receipt.is_file():
        payload = load_object(receipt)
        checks["FULL_SSOT_PACKAGE_RECEIPT.release_bound"] = payload.get("release") == release
        checks["FULL_SSOT_PACKAGE_RECEIPT.role"] = (
            payload.get("package_role") == "FULL_SSOT_CANONICAL"
        )
    return checks
