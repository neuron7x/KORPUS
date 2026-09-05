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
from korpus.application.provenance import compute_source_digest  # noqa: E402

PACKET = ROOT / "reports/OWNER_PILOT_RELEASE_PACKET.md"
LOAD = ROOT / "var/load-probe.json"
RECOVERY = ROOT / "var/recovery-report.json"
REGISTRY = ROOT / "reports/release/v0.9.7/final/BLOCKER_REGISTRY.json"
PREDICATES = ROOT / "reports/PRODUCTION_HARD_PREDICATES.json"

DIGEST_LINE = re.compile(r"^\*\*ДАЙДЖЕСТ ДЖЕРЕЛА:\*\* `([0-9a-f]{64})`", re.MULTILINE)
LOAD_TABLE = re.compile(r"\| холодний перший \|.*?\n\| сплеск \|[^\n]*\n", re.S)
RECOVERY_LINE = re.compile(r"^RTO \*\*[^\n]*\n", re.MULTILINE)
BLOCKER_BLOCK = re.compile(r"^`software_ready` \*\*[^\n]*\n", re.MULTILINE)


def _json(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _num(value: float) -> str:
    return f"{value:.3f}".replace(".", ",")


def load_table(load: dict[str, Any]) -> str:
    cold = load["cold_first_request"]
    rows = [
        f"| холодний перший | 1 | 1 | — | — | {cold['status']} за **{_num(cold['seconds'])} с** (стеля 5,0) |"
    ]
    for label, key, conc in (
        ("навантаження", "load", load["load"]["concurrency"]),
        ("**soak (за ним судять SLO)**", "soak", load["soak"]["concurrency"]),
        ("сплеск", "spike", load["spike"]["concurrency"]),
    ):
        phase = load[key]
        statuses = " · ".join(
            f"{count}×{code}" for code, count in sorted(phase["statuses"].items())
        )
        rows.append(
            f"| {label} | {conc} | {phase['requests']} | {_num(phase['p50_seconds'])} | "
            f"{_num(phase['p95_seconds'])} | {statuses} |"
        )
    return "\n".join(rows) + "\n"


def recovery_line(recovery: dict[str, Any]) -> str:
    return (
        f"RTO **{_num(recovery['rto_seconds'])} с** (відновлення {_num(recovery['restore_seconds'])}"
        f" + перевірка {_num(recovery['verify_seconds'])}) · RPO **{_num(recovery['rpo_seconds'])} с**"
        f" · втрачено подій {recovery['lost_events']} · клас масштабу `{recovery['scale_class']}`.\n"
    )


def blocker_line(registry: dict[str, Any], predicates: dict[str, Any]) -> str:
    counts = " · ".join(
        f"**{name}** {value}" for name, value in sorted(registry.get("counts", {}).items())
    )
    return (
        f"`software_ready` **{predicates.get('software_ready')} із "
        f"{predicates.get('predicates_total')}**. Реєстр блокерів: {counts}.\n"
    )


def _constant(value: str) -> Callable[[re.Match[str]], str]:
    """Заміна, яка не тлумачить свій текст.

    `re.sub` розгортає \\1 і \\g<...> у рядку заміни; числа з дайджеста або таблиці
    потрапили б під це правило мовчки. Функція повертає рядок дослівно.
    """

    def _replace(_match: re.Match[str]) -> str:
        return value

    return _replace


def render(text: str) -> str:
    digest = compute_source_digest(ROOT)
    load, recovery = _json(LOAD), _json(RECOVERY)
    registry, predicates = _json(REGISTRY), _json(PREDICATES)
    for pattern, replacement, label in (
        (DIGEST_LINE, f"**ДАЙДЖЕСТ ДЖЕРЕЛА:** `{digest}`", "прив'язка"),
        (LOAD_TABLE, load_table(load), "таблиця навантаження"),
        (RECOVERY_LINE, recovery_line(recovery), "числа відновлення"),
        (BLOCKER_BLOCK, blocker_line(registry, predicates), "стан блокерів"),
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
