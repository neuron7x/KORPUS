from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from korpus.application.release_truth import evidence_digest

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
    entries = [c for c in load_object(ledger).get("claims", ()) if isinstance(c, dict)]
    claims = [c for c in entries if str(c.get("status", "")).startswith("SUPPORTED")]
    unresolved = sum(1 for claim in claims if not _evidence_resolves(root, claim, release, digest))
    # `all([])` істинне: нуль підтриманих претензій задовольняв би обидві перевірки
    # тривіально. Порожній перелік — це UNKNOWN, а не досконалість.
    resolved = bool(claims) and unresolved == 0
    return {
        "CLAIM_LEDGER.supported_evidence_resolves": resolved,
        "CLAIM_LEDGER.supported_unresolved_zero": resolved,
        "CLAIM_LEDGER.has_supported_claims": bool(claims),
        # Решта онтології означає «не знаємо», не «ні»: вічне PENDING є дефектом.
        "CLAIM_LEDGER.every_claim_decided_by_evidence": bool(entries)
        and all(c.get("status") in ("SUPPORTED", "REFUTED_BY_EVIDENCE") for c in entries),
    }


#: Документ, на якому власник ухвалює рішення. Доти єдиний доказ релізу, якого не
#: звіряло НІЩО, і він двічі розійшовся з деревом мовчки. Повний облік — §16 пакета.
OWNER_PACKET = "reports/OWNER_PILOT_RELEASE_PACKET.md"

#: Рядок, якого в пакеті бути не сміє: він оголошує КОМІТ, а документ усередині дерева
#: назвати свій коміт не здатен — власна правка створює новий, і число застаріває тієї
#: ж миті. Тотожність коміта встановлює захищений тег власника, не проза в дереві.
#: `source_bound` цього не бачить за побудовою: `reports/` поза `EVIDENCE_SOURCE_PATHS`,
#: тож два коміти несуть один дайджест — критерій слабший за властивість, яку називає.
_CANDIDATE_CLAIM = re.compile(r"^\*\*КАНДИДАТ:\*\*\s*`?[0-9a-fA-F]{7,40}`?", re.MULTILINE)


def owner_packet_checks(root: Path, release: str, digest: str) -> dict[str, bool]:
    """Чи описує пакет власника ЦЕЙ кандидат.

    Назва релізу спільна для всіх кандидатів `v0.9.7` і сама по собі їх не розрізнить,
    тож в'яже дайджест дерева; четверта перевірка — про форму твердження, не значення.
    """
    path = root / OWNER_PACKET
    if not path.is_file():
        # Відсутній пакет — «власнику нема на чому вирішувати», не «скарг немає».
        return {f"{OWNER_PACKET}.present": False}
    text = path.read_text(encoding="utf-8", errors="ignore")
    return {
        f"{OWNER_PACKET}.present": True,
        f"{OWNER_PACKET}.release_bound": bool(release) and release in text,
        f"{OWNER_PACKET}.source_bound": bool(digest) and digest in text,
        f"{OWNER_PACKET}.no_unverifiable_candidate": not _CANDIDATE_CLAIM.search(text),
    }


#: Репродукція з ВІДДАЛЕНОГО джерела зі свіжими залежностями. Артефакт існував із
#: 05.09.2026 і не читався НІЧИМ: доказ без споживача не впливає ні на що, а виглядає
#: як частина вироку. Назвав незалежний верифікатор (VD-6).
CLEAN_ROOM = "reports/closure/CLEAN_ROOM_REPRODUCTION.json"


def clean_room_checks(root: Path, digest: str) -> dict[str, bool]:
    """Чи репродукція з remote описує ЦЕ дерево і чи вона пройшла.

    Відсутність артефакта — не мовчазна згода: `present: False` блокує так само, як
    `status != PASS`. Клас доказу перевіряється окремо, бо `verify-clean-clone` пише
    СЛАБШИЙ клас у інший файл, і сплутати їх означало б зарахувати клон із локального
    дерева за репродукцію з віддаленого.
    """
    path = root / CLEAN_ROOM
    if not path.is_file():
        return {f"{CLEAN_ROOM}.present": False}
    payload = load_object(path)
    pytest_block = payload.get("pytest")
    counted = isinstance(pytest_block, dict) and isinstance(pytest_block.get("tests"), int)
    return {
        f"{CLEAN_ROOM}.present": True,
        f"{CLEAN_ROOM}.status_pass": payload.get("status") == "PASS",
        f"{CLEAN_ROOM}.class_is_remote": payload.get("class") == "REMOTE_SOURCE_FRESH_DEPENDENCIES",
        f"{CLEAN_ROOM}.source_bound": bool(digest) and payload.get("source_tree_sha256") == digest,
        # Три перевірки вище стережуть САМООГОЛОШЕНІ скаляри: тризначний JSON
        # {status, class, source_tree_sha256} без жодного сліду відтворення проходив їх
        # усі. Довів незалежний верифікатор 06.09.2026 — гейт був живий (усі чотири
        # негативні контролі червоніли), але стеріг не той предмет.
        # Нижче — сліди самого ПРОГОНУ: скільки тестів виконано, скільки впало, який
        # коміт відтворювався і чи названо походження залежностей. Артефакт, що каже
        # PASS без жодного з них, більше не є доказом репродукції.
        f"{CLEAN_ROOM}.run_counted": counted and pytest_block["tests"] > 0,
        f"{CLEAN_ROOM}.run_clean": counted
        and pytest_block.get("failures") == 0
        and pytest_block.get("errors") == 0,
        f"{CLEAN_ROOM}.names_candidate": bool(payload.get("candidate_sha")),
        f"{CLEAN_ROOM}.names_dependency_origin": bool(payload.get("dependency_freeze_sha256")),
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
        # Усі перевірки вище читають те, що реєстр каже САМ ПРО СЕБЕ, і жодна не
        # відкриває його вхід — тож підміна змісту входу за тим самим шляхом лишалась
        # зеленою. `reports/` навмисно поза `source_tree_sha256`, тому прив'язка до
        # дерева змісту реєстру не визначає.
        "BLOCKER_REGISTRY.evidence_inputs_current": _evidence_inputs_current(root, payload),
    }


def _evidence_inputs_current(root: Path, payload: Mapping[str, Any]) -> bool:
    """Чи зібрано реєстр саме з ТИХ файлів доказів, які лежать зараз.

    Дайджест рахує ТА САМА функція, що його записала (`release_truth.evidence_digest`):
    два визначення одного відношення розійшлися б мовчки — рівно той клас, який ця
    перевірка й закриває рівнем вище. Зниклий файл дає порожній рядок, який не збігається
    з жодним записаним дайджестом. Порожній запис — НЕ згода: `all([])` істинне.
    """
    recorded = payload.get("evidence_sha256")
    if not isinstance(recorded, Mapping) or not recorded:
        return False
    return all(
        evidence_digest(root / str(relative)) == str(expected)
        for relative, expected in recorded.items()
    )
