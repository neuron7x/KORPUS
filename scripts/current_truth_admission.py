from __future__ import annotations

import json
from pathlib import Path

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


def claim_admission_checks(root: Path, release: str, digest: str) -> dict[str, bool]:
    ledger = root / f"reports/release/{release}/final/CLAIM_LEDGER.json"
    if not ledger.is_file():
        return {"CLAIM_LEDGER.supported_evidence_resolves": False}
    unresolved = 0
    for claim in load_object(ledger).get("claims", ()):
        if not isinstance(claim, dict) or not str(claim.get("status", "")).startswith("SUPPORTED"):
            continue
        evidence = claim.get("evidence")
        if not isinstance(evidence, str) or not evidence:
            unresolved += 1
            continue
        target = root / evidence
        if not target.is_file() or (
            target.suffix == ".json" and not _current_json(target, release, digest)
        ):
            unresolved += 1
    # `all([])` істинне: нуль підтриманих претензій задовольняв би обидві перевірки
    # тривіально. Порожній перелік — це UNKNOWN, а не досконалість.
    supported = sum(
        1
        for claim in load_object(ledger).get("claims", ())
        if isinstance(claim, dict) and str(claim.get("status", "")).startswith("SUPPORTED")
    )
    return {
        "CLAIM_LEDGER.supported_evidence_resolves": supported > 0 and unresolved == 0,
        "CLAIM_LEDGER.supported_unresolved_zero": supported > 0 and unresolved == 0,
        "CLAIM_LEDGER.has_supported_claims": supported > 0,
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
    }
