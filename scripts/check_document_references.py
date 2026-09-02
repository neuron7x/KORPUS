#!/usr/bin/env python3
"""Документ не сміє називати файл, якого немає.

ВИМІРЯНО 02.09.2026. `docs/audit/DESTRUCTION_STAGE_2026-08-05.md` подавав числа —
«73×», «882 недоставлені контрольні точки», таблицю 257/449/448 подій/с — і називав
джерелом кожного виміру три скрипти:

    scripts/attack_span_listing.py · attack_anchor_backlog.py · attack_audit_throughput.py

Жоден із трьох не існував НІКОЛИ: `git log --all --diff-filter=A` порожній для всіх,
а в `scripts/` немає жодного скрипта атаки взагалі. Тобто стадія руйнування, яку
`feedback_mandatory_destruction_stage` робить обов'язковою перед злиттям, мала звіт із
числами й не мала інструмента. Помічене подавалось як виміряне, і форма звіту це ховала.

ЧОМУ РОЗВ'ЯЗУЮТЬСЯ СКОРОЧЕННЯ. Перша версія цієї перевірки вимагала, щоб кожен
згаданий шлях існував дослівно, і дала **242** знахідки на 242 — документи законно
пишуть `composition.py` замість `apps/api/src/korpus/application/composition.py`.
Перевірка, чиї знахідки доводиться перебирати, гірша за відсутню, тому посилання
вважається розв'язаним, якщо БОДАЙ ОДИН відстежений шлях ним закінчується. 242 → 15.

ЧОМУ МАРКЕР У ТЕКСТІ, А НЕ РЕЄСТР ВИНЯТКІВ. З тих 15 дванадцять — чесні згадки про
ВИДАЛЕНЕ: «`REPOSITORY_MANIFEST.json` прибрано», перелік модулів, знятих під час
зведення. Реєстр виправдань створив би збочений стимул: написати «X прибрано» ставало б
дорожче, ніж змовчати. Тому виправдовує САМ ТЕКСТ — абзац, що каже про видалення, або
банер документа. Автор, який пише правду про видалене, задовольняє гейт тим самим
реченням, яким він її пише. 15 → 6, і всі шість — саме такі згадки, яким бракує слова.

НЕГАТИВНИЙ КОНТРОЛЬ ПРОЙДЕНО НА ЖИВОМУ ВИПАДКУ: на версії
`DESTRUCTION_STAGE_2026-08-05.md` з `HEAD` (до того, як документ дістав банер) перевірка
ловить усі три вигадані скрипти. Це не приклад із докстрінга — це прогін.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: Посилання у зворотних лапках, схоже на шлях до файла.
_REFERENCE = re.compile(
    r"`([a-zA-Z0-9_][\w./-]*\.(?:py|sh|json|yaml|yml|md|mjs|ts|toml|ini|xml|jsonl|conf|bundle))`"
)

#: Слова, якими текст САМ каже, що названого більше немає.
_GONE = re.compile(
    r"видален|прибран|removed|deleted|більше немає|не існу|немає|НЕМАЄ|історичн|historical"
    r"|застаріл|superseded|no longer|не існували|ЗАМОРОЖЕН",
    re.I,
)

#: Банер документа: рядок цитати з червоною позначкою в перших тридцяти рядках.
_BANNER = re.compile(r"^>.*(⛔|🔴)", re.M)

_AREAS = ("*.md", "docs/**/*.md", "handoff/**/*.md")

#: Артефакти ПРОГОНУ. Їх немає ні в чистому клоні, ні в продакшенному образі, ні в
#: пісочниці проби — і це нормально: їх виробляють, а не тримають. Посилання на них
#: судити не можна, інакше гейт червонів би скрізь, де ще нічого не запускали.
#: Виміряно 02.09.2026 власною отрутою: `var/recovery-report.json` валив чистий стан.
_GENERATED = ("var/", "reports/", "dist/", "htmlcov/", "handoff/evidence/")


def _described(root: Path) -> list[str] | None:
    """Опис дерева з git, інакше з маніфесту, інакше НІЧОГО — і це відмова, не порожнеча.

    ВИМІРЯНО 02.09.2026 власною отрутою живучості. Перша версія питала лише
    `git ls-files`, а проба копіює дерево БЕЗ `.git`: перелік ставав порожнім, і кожне
    скорочене посилання читалось як мертве. Гейт червонів би в пісочниці, у продакшенному
    образі й у чистій розпакованій копії — усюди, де git відсутній ЗА ПОБУДОВОЮ.
    """
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files"], capture_output=True, text=True, check=False
    )
    if result.returncode == 0:
        tracked = [line for line in result.stdout.split("\n") if line]
        if tracked:
            return tracked
    manifest = root / "SOURCE_MANIFEST.json"
    if not manifest.is_file():
        return None
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entries = payload.get("files")
    if not isinstance(entries, list):
        return None
    names = [str(item["path"]) for item in entries if isinstance(item, dict) and item.get("path")]
    return names or None


def _on_disk(root: Path) -> list[str]:
    """Що справді лежить у дереві. Прямий доказ існування, а не опис.

    Потрібен окремо від опису, бо ОПИС не містить сам себе: `SOURCE_MANIFEST.json`,
    `DISTRIBUTION_MANIFEST.json` і `FULL_SSOT_PACKAGE_RECEIPT.json` у маніфесті не
    перелічені, і без цієї гілки тринадцять чинних посилань читались як мертві.
    """
    # Обсяг РОЗВ'ЯЗАННЯ навмисно ширший за обсяг СУДЖЕННЯ. Виміряно 02.09.2026: коли
    # `handoff/evidence/` виключили й тут, скорочене посилання `MANIFEST.json` (насправді
    # `handoff/evidence/current/MANIFEST.json`, файл відстежений і наявний) стало мертвим
    # у пісочниці й живим на дереві з git. Не судити артефакт прогону — це одне рішення;
    # не знати, що він існує, — зовсім інше, і друге лише плодить хибні тривоги.
    skip = (".git/", "node_modules/", ".venv/", "apps/api/.venv/")
    found: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = str(path.relative_to(root))
        if relative.startswith(skip):
            continue
        found.append(relative)
    return found


def _inventory(root: Path) -> list[str] | None:
    described = _described(root)
    if described is None:
        return None
    return sorted(set(described) | set(_on_disk(root)))


def _resolves(reference: str, tracked: list[str], root: Path) -> bool:
    """Дослівний шлях, файл на диску, або будь-який відстежений шлях із таким хвостом."""
    if reference in tracked or (root / reference).exists():
        return True
    tail = "/" + reference
    return any(path.endswith(tail) for path in tracked)


def _excused_document(text: str) -> bool:
    head = "\n".join(text.splitlines()[:30])
    return bool(_BANNER.search(head)) and bool(_GONE.search(head))


def documents(root: Path) -> list[Path]:
    found: list[Path] = []
    for pattern in _AREAS:
        found.extend(root.glob(pattern))
    return sorted(set(found))


def observe(root: Path = ROOT) -> list[dict[str, str]] | None:
    """Посилання, які нікуди не ведуть і яких текст не оголосив видаленими."""
    tracked = _inventory(root)
    if tracked is None:
        return None
    dead: list[dict[str, str]] = []
    for document in documents(root):
        try:
            text = document.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover - нечитаний файл
            continue
        if _excused_document(text):
            continue
        for paragraph in re.split(r"\n\s*\n", text):
            if _GONE.search(paragraph):
                continue
            for reference in sorted(set(_REFERENCE.findall(paragraph))):
                if reference.startswith(_GENERATED):
                    continue
                if not _resolves(reference, tracked, root):
                    dead.append(
                        {"document": str(document.relative_to(root)), "reference": reference}
                    )
    return dead


def assess(dead: list[dict[str, str]] | None, scanned: int) -> dict[str, Any]:
    if dead is None:
        return {
            "status": "UNKNOWN",
            "scanned": scanned,
            "dead": [],
            "problems": [
                "дерево не описане ні git, ні SOURCE_MANIFEST.json — обсяг невідомий, "
                "а невідомий обсяг не дорівнює порожньому"
            ],
        }
    if scanned == 0:
        return {
            "status": "UNKNOWN",
            "scanned": 0,
            "dead": [],
            "problems": ["жодного документа не знайдено — це зламаний пошук, не чисте дерево"],
        }
    problems = [
        f"{item['document']} називає `{item['reference']}`, якого в дереві немає, "
        "і не каже, що його прибрано"
        for item in dead
    ]
    return {
        "status": "FAIL" if problems else "PASS",
        "scanned": scanned,
        "dead": dead,
        "problems": problems,
    }


def _selftest() -> int:
    cases: list[tuple[list[dict[str, str]] | None, int, str, str]] = [
        (None, 12, "UNKNOWN", "дерево не описане — не PASS"),
        ([], 0, "UNKNOWN", "нуль документів — не PASS"),
        ([], 12, "PASS", "жодного мертвого посилання"),
        ([{"document": "d.md", "reference": "ghost.py"}], 12, "FAIL", "мертве посилання"),
    ]
    for dead, scanned, expected, label in cases:
        got = assess(dead, scanned)["status"]
        if got != expected:
            print(json.dumps({"selftest": "FAIL", "case": label, "got": got}, ensure_ascii=False))
            return 1
    # Розв'язання скорочень: без нього перевірка кричить вовк на 242 місцях із 242.
    tracked = ["apps/api/src/korpus/application/composition.py"]
    if _inventory(Path("/nonexistent")) is not None:
        print(
            json.dumps(
                {"selftest": "FAIL", "case": "дерево без опису визнано описаним"},
                ensure_ascii=False,
            )
        )
        return 1
    if not _resolves("composition.py", tracked, Path("/nonexistent")):
        print(
            json.dumps({"selftest": "FAIL", "case": "скорочення не розв'язане"}, ensure_ascii=False)
        )
        return 1
    if _resolves("ghost.py", tracked, Path("/nonexistent")):
        print(
            json.dumps(
                {"selftest": "FAIL", "case": "неіснуюче визнано наявним"}, ensure_ascii=False
            )
        )
        return 1
    # Хвіст мусить збігатися по МЕЖІ теки, інакше `position.py` розв'язав би `sition.py`.
    if not "var/recovery-report.json".startswith(_GENERATED):
        print(
            json.dumps(
                {"selftest": "FAIL", "case": "артефакт прогону не виключено"}, ensure_ascii=False
            )
        )
        return 1
    if "docs/x.md".startswith(_GENERATED):
        print(
            json.dumps(
                {"selftest": "FAIL", "case": "джерельний шлях виключено як артефакт"},
                ensure_ascii=False,
            )
        )
        return 1
    if _resolves("sition.py", ["a/composition.py"], Path("/nonexistent")):
        print(json.dumps({"selftest": "FAIL", "case": "хвіст без межі теки"}, ensure_ascii=False))
        return 1
    # Банер документа виправдовує, відсутність банера — ні.
    banner = "# Х\n\n> ## 🔴 ЧИСЛА НЕ МАЮТЬ ПІДСТАВИ: інструментів не існувало\n"
    if not _excused_document(banner):
        print(json.dumps({"selftest": "FAIL", "case": "банер не виправдав"}, ensure_ascii=False))
        return 1
    if _excused_document("# Х\n\nЗвичайний текст із `ghost.py`.\n"):
        print(
            json.dumps(
                {"selftest": "FAIL", "case": "документ без банера виправданий"}, ensure_ascii=False
            )
        )
        return 1
    print(json.dumps({"selftest": "PASS"}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--out", type=Path)
    arguments = parser.parse_args()
    if arguments.selftest:
        return _selftest()
    report = assess(observe(), len(documents(ROOT)))
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if arguments.out:
        arguments.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
