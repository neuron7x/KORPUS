from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

try:
    from .current_truth_contract import load_object
except ImportError:  # direct script execution with scripts/ on sys.path
    from current_truth_contract import load_object


def _current_json(path: Path, release: str, digest: str) -> bool:
    try:
        payload = load_object(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if "release" in payload and payload.get("release") != release:
        return False
    # Прив'язка читається З ОБОХ місць: верхній рівень і канонічний конверт
    # `provenance`, який ставить `korpus.application.provenance.stamp`. Читач, що знає
    # лише верхній рівень, оголошує неприв'язаним усе, що прив'язане конвертом —
    # а конверт у цьому дереві стандарт, не виняток.
    top = payload.get("source_tree_sha256", payload.get("source_digest"))
    envelope = payload.get("provenance")
    inner = envelope.get("source_digest") if isinstance(envelope, dict) else None
    top = top if isinstance(top, str) else None
    inner = inner if isinstance(inner, str) else None
    if top is not None and inner is not None and top != inner:
        # Дві прив'язки розійшлись: це не «поточне» й не «застаріле», а стан, у якому
        # артефакт сам собі суперечить. Згоди тут немає, тож і зарахування немає.
        return False
    bound = top if top is not None else inner
    # Відсутність прив'язки — це «не знаю», а не «поточне». Раніше тут стояло
    # `bound is None or bound == digest`, тож артефакт без прив'язки зараховувався як
    # такий, що описує це дерево. Разом із `release_claims` це давало ланцюг, де
    # ВІДСУТНІСТЬ читалась як згода на ОБОХ кінцях.
    return bound is not None and bound == digest


def _evidence_resolves(root: Path, claim: dict[str, object], release: str, digest: str) -> bool:
    """Чи веде претензія до доказу, який описує САМЕ це дерево."""
    evidence = claim.get("evidence")
    if not isinstance(evidence, str) or not evidence:
        return False
    target = root / evidence
    if not target.is_file():
        return False
    return target.suffix != ".json" or _current_json(target, release, digest)


def claim_admission_checks(root: Path, release: str, digest: str) -> dict[str, bool]:
    ledger = root / f"reports/release/{release}/final/CLAIM_LEDGER.json"
    if not ledger.is_file():
        return {"CLAIM_LEDGER.supported_evidence_resolves": False}
    # Журнал читається ОДИН раз. Перша редакція викликала `load_object` двічі — і це не
    # лише подвійна робота: два читання одного файла можуть дати різний вміст, якщо між
    # ними хтось пише, і тоді два числа описують два різні журнали.
    claims = [
        claim
        for claim in load_object(ledger).get("claims", ())
        if isinstance(claim, dict) and str(claim.get("status", "")).startswith("SUPPORTED")
    ]
    unresolved = sum(1 for claim in claims if not _evidence_resolves(root, claim, release, digest))
    # `all([])` істинне: нуль підтриманих претензій задовольняв би обидві перевірки
    # тривіально. Порожній перелік — це UNKNOWN, а не досконалість.
    resolved = bool(claims) and unresolved == 0
    return {
        "CLAIM_LEDGER.supported_evidence_resolves": resolved,
        "CLAIM_LEDGER.supported_unresolved_zero": resolved,
        "CLAIM_LEDGER.has_supported_claims": bool(claims),
    }


def blocker_state_checks(root: Path, release: str, digest: str) -> dict[str, bool]:
    path = root / f"reports/release/{release}/final/BLOCKER_REGISTRY.json"
    if not path.is_file():
        return {"BLOCKER_REGISTRY.current_state_present": False}
    payload = load_object(path)
    return {
        "BLOCKER_REGISTRY.current_state_present": True,
        "BLOCKER_REGISTRY.hard_predicate_report_current": payload.get(
            "hard_predicate_report_current"
        )
        is True,
        "BLOCKER_REGISTRY.internal_executable_unresolved_zero": payload.get(
            "internal_executable_unresolved"
        )
        == 0,
        "BLOCKER_REGISTRY.source_bound_current": payload.get("source_tree_sha256") == digest,
        "BLOCKER_REGISTRY.release_bound_current": payload.get("release") == release,
        # Прив'язка до ДЕРЕВА не визначає змісту реєстру: його стани виводяться з
        # `reports/PRODUCTION_HARD_PREDICATES.json`, а `reports/` навмисно виключено
        # з `source_tree_sha256`. Виміряно 04.09.2026: реєстр кандидата був зібраний
        # на шість годин раніше за свій же доказ, і перезбирання на НЕЗМІННОМУ дереві
        # перевело 7 блокерів у CLOSED_ANCHORED. Прив'язка трималась, зміст розійшовся.
        "BLOCKER_REGISTRY.evidence_inputs_current": _evidence_inputs_current(root, payload),
    }


def _evidence_inputs_current(root: Path, payload: Mapping[str, Any]) -> bool:
    """Чи зібрано реєстр саме з ТИХ файлів доказів, які лежать зараз.

    Порожній запис — НЕ згода: реєстр без переліку входів не називає, з чого зібраний,
    і невимірене не є пройденим.
    """
    recorded = payload.get("evidence_sha256")
    if not isinstance(recorded, Mapping) or not recorded:
        return False
    for relative, expected in recorded.items():
        path = root / str(relative)
        if not path.is_file():
            return False
        if hashlib.sha256(path.read_bytes()).hexdigest() != str(expected):
            return False
    return True
