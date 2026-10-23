from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from korpus.application.release_truth import blocker_registry, evidence_digest

try:
    from .clean_room_contract import clean_room_contract
    from .current_truth_claims import claim_admission_checks as claim_admission_checks
    from .current_truth_contract import (
        OWNER_METADATA_PREFIX,
        OWNER_METADATA_SCHEMA,
        OWNER_METADATA_STATUS,
        load_object,
    )
except ImportError:  # direct script execution with scripts/ on sys.path
    from clean_room_contract import clean_room_contract
    from current_truth_claims import claim_admission_checks as claim_admission_checks
    from current_truth_contract import (
        OWNER_METADATA_PREFIX,
        OWNER_METADATA_SCHEMA,
        OWNER_METADATA_STATUS,
        load_object,
    )


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


#: Документ, на якому власник ухвалює рішення. Доти єдиний доказ релізу, якого не
#: звіряло НІЩО, і він двічі розійшовся з деревом мовчки. Повний облік — §16 пакета.
OWNER_PACKET = "reports/OWNER_PILOT_RELEASE_PACKET.md"
_OWNER_METADATA_FIELDS = frozenset(
    {"schema", "status", "release", "source_tree_sha256", "digest_scope"}
)
_OWNER_METADATA = re.compile(
    rf"^<!-- {OWNER_METADATA_PREFIX} (?P<payload>{{[^\n]*}}) -->$", re.MULTILINE
)

#: Рядок, якого в пакеті бути не сміє: він оголошує КОМІТ, а документ усередині дерева
#: назвати свій коміт не здатен — власна правка створює новий, і число застаріває тієї
#: ж миті. Тотожність коміта встановлює захищений тег власника, не проза в дереві.
#: `source_bound` цього не бачить за побудовою: `reports/` поза `EVIDENCE_SOURCE_PATHS`,
#: тож два коміти несуть один дайджест — критерій слабший за властивість, яку називає.
_CANDIDATE_CLAIM = re.compile(r"^\*\*КАНДИДАТ:\*\*\s*`?[0-9a-fA-F]{7,40}`?", re.MULTILINE)


def _without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate owner metadata key: {key}")
        payload[key] = value
    return payload


def _owner_metadata(text: str) -> tuple[dict[str, Any] | None, bool]:
    matches = list(_OWNER_METADATA.finditer(text))
    if len(matches) != 1:
        return None, False
    try:
        payload = json.loads(matches[0].group("payload"), object_pairs_hook=_without_duplicate_keys)
    except (json.JSONDecodeError, ValueError):
        return None, True
    return (payload if isinstance(payload, dict) else None), True


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
    metadata, unique = _owner_metadata(text)
    values = metadata or {}
    exact = metadata is not None and set(values) == _OWNER_METADATA_FIELDS
    return {
        f"{OWNER_PACKET}.present": True,
        f"{OWNER_PACKET}.metadata_unique": unique,
        f"{OWNER_PACKET}.metadata_exact": exact,
        f"{OWNER_PACKET}.schema_exact": exact and values.get("schema") == OWNER_METADATA_SCHEMA,
        f"{OWNER_PACKET}.status_current": exact and values.get("status") == OWNER_METADATA_STATUS,
        f"{OWNER_PACKET}.scope_named": exact and values.get("digest_scope") == "evidence_paths",
        f"{OWNER_PACKET}.release_bound": exact
        and bool(release)
        and values.get("release") == release,
        f"{OWNER_PACKET}.source_bound": exact
        and bool(digest)
        and values.get("source_tree_sha256") == digest,
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
    checks = clean_room_contract(root, load_object(path), digest)
    return {
        f"{CLEAN_ROOM}.present": True,
        **{f"{CLEAN_ROOM}.{key}": value for key, value in checks.items()},
    }


def _expected_registry(root: Path, release: str, digest: str) -> dict[str, Any] | None:
    try:
        return blocker_registry(root, digest, release)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


def blocker_state_checks(root: Path, release: str, digest: str) -> dict[str, bool]:
    path = root / f"reports/release/{release}/final/BLOCKER_REGISTRY.json"
    if not path.is_file():
        return {"BLOCKER_REGISTRY.current_state_present": False}
    payload = load_object(path)
    expected = _expected_registry(root, release, digest)
    exact_fields = set(expected or {}) - {"generated_at"}
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
        "BLOCKER_REGISTRY.recomputed_exact": all(
            payload.get(field) == expected[field] for field in exact_fields
        )
        if expected is not None
        else False,
        "BLOCKER_REGISTRY.production_status_coherent": payload.get("status") == expected["status"]
        if expected is not None
        else False,
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
