from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from korpus.application.provenance import DIGEST_SCOPE, PROVENANCE_KEY


def binding(payload: dict[str, Any]) -> tuple[str | None, bool]:
    """Прив'язка доказу до дерева: з ВЕРХНЬОГО рівня або з канонічного конверта.

    Повертає `(дайджест | None, розбіжність)`.

    Перша редакція цієї перевірки читала лише верхній рівень і оголосила
    `reports/MUTATION_FULL_CATALOGUE_CURRENT.json` неприв'язаним. Він прив'язаний: його
    дайджест лежить у `provenance.source_digest` — у конверті, який ставить
    `korpus.application.provenance.stamp` і читає `read_provenance`, і який у цьому дереві
    є СТАНДАРТОМ, а не винятком.

    Це та сама вада, заради якої писалась ця функція, лише дзеркальна: там ВІДСУТНІСТЬ
    читалась як згода, тут НАЯВНІСТЬ читалась як відсутність. Хибна відмова коштує
    стільки ж, скільки хибне підтвердження, і помічається гірше — бо виглядає обережно.

    Розбіжність між двома джерелами повертається окремим прапорцем, а не мовчазним
    вибором сильнішого: два оголошення одного факту, які розійшлись, — це стан, про який
    треба сказати, а не залагодити. `or` тут дав би застарілість замість розбіжності.
    """
    top = payload.get("source_tree_sha256", payload.get("source_digest"))
    envelope = payload.get(PROVENANCE_KEY)
    inner = envelope.get("source_digest") if isinstance(envelope, dict) else None
    top = top if isinstance(top, str) else None
    inner = inner if isinstance(inner, str) else None
    if top is not None and inner is not None and top != inner:
        return None, True
    return (top if top is not None else inner), False


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
    bound, divergent = binding(payload)
    if divergent:
        # Два оголошення однієї прив'язки розійшлись. Слабше не перемагає мовчки.
        return "DIVERGENT_BINDING"
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
            "reports/SOURCE_MANIFEST_VERIFICATION_CURRENT.json",
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
    # Доти обидві несли вписаний у код "REFUTED": правдивий і НЕФАЛЬСИФІКОВНИЙ разом.
    registry = f"reports/release/{release}/final/BLOCKER_REGISTRY.json"
    rendered.extend(
        [
            {
                "id": i,
                "claim": c,
                "status": _claim_status(root, registry, source_digest, release),
                "evidence": registry,
            }
            for i, c in (
                ("CLM-PRODUCTION-AUTH", "System is production-authorized."),
                ("CLM-INDEPENDENT", "System is independently validated."),
            )
        ]
    )
    return {
        "schema": "korpus.claim-ledger.v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "release": release,
        "source_tree_sha256": source_digest,
        "digest_scope": DIGEST_SCOPE,
        "claims": rendered,
    }
