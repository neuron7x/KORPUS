#!/usr/bin/env python3
"""Тримає ВИМІРЯНІ частини пакета власника рівними артефактам — і вміє це перевірити.

Пакет `reports/OWNER_PILOT_RELEASE_PACKET.md` — єдина поверхня, на яку дивиться
ЛЮДИНА, і `verify_current_truth` гейтує його `source_bound`. Але виробника в дереві
не було: числа й дайджест правились рукою, і пакет розійшовся з виміром тричі за
півдня — це записано в §16 самого пакета.

Тут не генерується весь документ: судження власника (§3 знаменник, §5 критерії
зупинки пілоту, §6 рішення, яких він не ухвалював) належать людині й не мають
машинного джерела. Оновлюються рівно ті блоки, під якими лежить артефакт:
прив'язка, таблиця навантаження, числа відновлення, стан блокерів.

    refresh_owner_packet.py            оновити
    refresh_owner_packet.py --check    не писати; rc=1, якщо розійшлося

`--check` існує, щоб розбіжність ловилась ДО того, як власник прочитає число:
гейт `source_bound` бачить лише дайджест, а не те, чи числа під ним про це дерево.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))
from current_truth_contract import (  # noqa: E402
    OWNER_METADATA_PREFIX,
    owner_metadata_line,
)
from korpus.application.provenance import compute_source_digest  # noqa: E402
from owner_packet_measurements import load_block, recovery_block  # noqa: E402

PACKET = ROOT / "reports/OWNER_PILOT_RELEASE_PACKET.md"
LOAD = ROOT / "var/load-probe.json"
RECOVERY = ROOT / "var/recovery-report.json"
REGISTRY = ROOT / "reports/release/v0.9.7/final/BLOCKER_REGISTRY.json"
PREDICATES = ROOT / "reports/PRODUCTION_HARD_PREDICATES.json"

DIGEST_LINE = re.compile(r"^\*\*ДАЙДЖЕСТ ДЖЕРЕЛА:\*\* `([0-9a-f]{64})`", re.MULTILINE)
METADATA_LINE = re.compile(rf"^<!-- {OWNER_METADATA_PREFIX}\b[^\n]*-->$", re.MULTILINE)
FIRST_HEADING = re.compile(r"^(#[^\n]*\n)", re.MULTILINE)
LOAD_TABLE = re.compile(r"\| холодний перший \|.*?\n\| сплеск \|[^\n]*\n", re.S)
RECOVERY_LINE = re.compile(r"^RTO \*\*[^\n]*\n", re.MULTILINE)
#: Заголовок ВХОДИТЬ у проліт навмисно. Доти блок починався з `software_ready`, тож
#: `--check` оновлював ЧИСЛО і не чіпав дату й дайджест, якими це число підписане:
#: найсвіжіший вимір стояв під штампом чужого дерева (`b9096028` при дереві `0be621c1`),
#: і читач прив'язував правильне число до неправильного предмета. Виміряно незалежною
#: сесією 06.09.2026: проліт накривав 10 рядків із 680, і жодне твердження про число
#: блокерів у них не потрапляло.
#: Лічильник кандидата. Він жив у §3 ЧОТИРМА написаннями від руки («блокерів кандидата
#: нуль» проти «доки блокерів §3 п'ять»), і документ суперечив сам собі в межах одного
#: файла. Рішення власника про ОБСЯГ лишається прозою; лічильник має виробника.
CANDIDATE_LINE = re.compile(r"^`blocks_candidate` \*\*[^\n]*\n", re.MULTILINE)
BLOCKER_BLOCK = re.compile(r"^### 2\.6-BIS [^\n]*\n\n`software_ready` \*\*[^\n]*\n", re.MULTILINE)


def blocker_line(registry: dict[str, Any], predicates: dict[str, Any]) -> str:
    counts = " · ".join(
        f"**{name}** {value}" for name, value in sorted(registry.get("counts", {}).items())
    )
    stamp = str(registry.get("generated_at", ""))[:10] or "дата не записана"
    digest = str(registry.get("source_tree_sha256", ""))[:16] or "дайджест не записаний"
    return (
        f"### 2.6-BIS Стан блокерів (вимір {stamp}, дайджест `{digest}`)\n\n"
        f"`software_ready` **{predicates.get('software_ready')} із "
        f"{predicates.get('predicates_total')}**. Реєстр блокерів: {counts}.\n"
    )


def candidate_line(predicates: dict[str, Any]) -> str:
    """Скільки предикатів БЛОКУЮТЬ кандидата — і які саме."""
    states = [row for row in predicates.get("states", []) if isinstance(row, dict)]
    blocking = sorted(str(row.get("id")) for row in states if row.get("blocks_candidate"))
    external = sum(1 for row in states if not row.get("externally_satisfied"))
    named = ", ".join(f"`{name}`" for name in blocking) if blocking else "жодного"
    return (
        f"`blocks_candidate` **{len(blocking)}** · зовнішніх вимог "
        f"**{external} із {len(states)}**. Блокують: {named}.\n"
    )


def _constant(value: str) -> Callable[[re.Match[str]], str]:
    """Заміна, яка не тлумачить свій текст.

    `re.sub` розгортає \\1 і \\g<...> у рядку заміни; числа з дайджеста або таблиці
    потрапили б під це правило мовчки. Функція повертає рядок дослівно.
    """

    def _replace(_match: re.Match[str]) -> str:
        return value

    return _replace


def bind_metadata(text: str, metadata_line: str) -> str:
    """Оновити єдиний машинний конверт; проза не є прив'язкою."""
    matches = list(METADATA_LINE.finditer(text))
    if len(matches) > 1:
        raise SystemExit("у пакеті більше одного machine-readable metadata конверта")
    if matches:
        return METADATA_LINE.sub(_constant(metadata_line), text, count=1)
    if OWNER_METADATA_PREFIX in text:
        raise SystemExit("пошкоджений machine-readable metadata конверт пакета")
    heading = FIRST_HEADING.search(text)
    if heading is None:
        raise SystemExit("якоря немає в пакеті: заголовок")
    return f"{text[: heading.end()]}\n{metadata_line}\n{text[heading.end() :]}"


def render(text: str) -> str:
    digest = compute_source_digest(ROOT)
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    predicates = json.loads(PREDICATES.read_text(encoding="utf-8"))
    release = str(registry.get("release", ""))
    text = bind_metadata(text, owner_metadata_line(release, digest))
    for pattern, replacement, label in (
        (DIGEST_LINE, f"**ДАЙДЖЕСТ ДЖЕРЕЛА:** `{digest}`", "прив'язка"),
        (LOAD_TABLE, load_block(LOAD, digest, release), "таблиця навантаження"),
        (RECOVERY_LINE, recovery_block(RECOVERY, digest, release), "числа відновлення"),
        (BLOCKER_BLOCK, blocker_line(registry, predicates), "стан блокерів"),
        (CANDIDATE_LINE, candidate_line(predicates), "лічильник кандидата"),
    ):
        if not pattern.search(text):
            raise SystemExit(f"якоря немає в пакеті: {label}")
        text = pattern.sub(_constant(replacement), text, count=1)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    current = PACKET.read_text(encoding="utf-8")
    updated = render(current)
    if arguments.check:
        if current == updated:
            print(
                json.dumps(
                    {"status": "PASS", "packet": str(PACKET.relative_to(ROOT))}, ensure_ascii=False
                )
            )
            return 0
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "packet": str(PACKET.relative_to(ROOT)),
                    "detail": "виміряні блоки пакета розійшлися з артефактами; `make owner-packet`",
                },
                ensure_ascii=False,
            )
        )
        return 1
    PACKET.write_text(updated, encoding="utf-8")
    print(
        json.dumps(
            {"status": "WRITTEN", "packet": str(PACKET.relative_to(ROOT))}, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
