from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _claim_status(root: Path, evidence: str, source_digest: str, release: str) -> str:
    path = root / evidence
    if not path.is_file():
        return "PENDING_EVIDENCE"
    if path.suffix != ".json":
        # Файл, якого ця функція не вміє прочитати, не є доказом «за». Раніше тут стояло
        # `return "SUPPORTED"` — тобто претензія ставала підтриманою, НЕ ПРОЧИТАВШИ
        # жодного байта. Доведено побудовою 02.09.2026: порожній `.txt` давав SUPPORTED.
        return "UNDECLARED_EVIDENCE"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "INVALID_EVIDENCE"
    if not isinstance(payload, dict):
        return "INVALID_EVIDENCE"
    if "release" in payload and payload.get("release") != release:
        return "STALE_EVIDENCE"
    bound = payload.get("source_tree_sha256", payload.get("source_digest"))
    if bound is None:
        # Доказ БЕЗ прив'язки не є доказом про це дерево. Раніше умова була
        # `bound is not None and bound != source_digest`, тож відсутність прив'язки
        # проходила повз перевірку застарілості цілком.
        return "UNBOUND_EVIDENCE"
    if bound != source_digest:
        return "STALE_EVIDENCE"
    semantic = payload.get("status", payload.get("verdict"))
    if semantic is None:
        # Артефакт, який не оголошує вироку, не виносить його мовчки. Раніше `None`
        # стояв у тому самому кортежі, що й "PASS".
        return "UNDECLARED_EVIDENCE"
    return (
        "SUPPORTED"
        if semantic in ("PASS", "PASS_WITH_EXTERNAL_BLOCKERS")
        else "REFUTED_BY_EVIDENCE"
    )


def claim_ledger(root: Path, source_digest: str, release: str) -> dict[str, Any]:
    claims = [
        (
            "CLM-SOURCE-INTEGRITY",
            "Current source manifest is the release source boundary.",
            "SOURCE_MANIFEST.json",
        ),
        (
            "CLM-REGRESSION",
            "Current backend regression is source-bound and failure-free.",
            f"reports/release/{release}/FULL_BACKEND_REPORT.json",
        ),
        (
            "CLM-WEB",
            "Current web lint/build/test surface is source-bound and failure-free.",
            f"reports/release/{release}/WEB_REGRESSION_REPORT.json",
        ),
        (
            "CLM-MUTATION",
            "Declared full mutation catalogue has no surviving valid mutants.",
            "reports/MUTATION_FULL_CATALOGUE_CURRENT.json",
        ),
        (
            "CLM-INFERENCE-SECURITY",
            "Current inference-security suite passes its declared attack surface.",
            f"reports/release/{release}/INFERENCE_SECURITY_GATE.json",
        ),
    ]
    rendered = [
        {
            "id": i,
            "claim": c,
            "status": _claim_status(root, e, source_digest, release),
            "evidence": e,
        }
        for i, c, e in claims
    ]
    rendered.extend(
        [
            {
                "id": "CLM-PRODUCTION-AUTH",
                "claim": "System is production-authorized.",
                "status": "REFUTED",
                "evidence": f"reports/release/{release}/final/BLOCKER_REGISTRY.json",
            },
            {
                "id": "CLM-INDEPENDENT",
                "claim": "System is independently validated.",
                "status": "REFUTED",
                "evidence": f"reports/release/{release}/final/BLOCKER_REGISTRY.json",
            },
        ]
    )
    return {
        "schema": "korpus.claim-ledger.v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "release": release,
        "source_tree_sha256": source_digest,
        "claims": rendered,
    }
