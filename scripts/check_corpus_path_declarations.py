#!/usr/bin/env python3
"""Шлях до корпусу оголошено багато разів. Вада — не в кількості, а в РОЗХОДЖЕННІ.

ВИМІРЯНО 02.09.2026. Шлях до бази, яку публічний сайт подає солдату, оголошений у
дереві **22 рази** незалежно. Дев'ятнадцять кажуть
`var/runtime/corpus-v6-20260807/korpus.db`. Три кажуть `var/korpus-ml.db` — файла з
таким іменем у дереві НЕМАЄ:

    scripts/backup_sqlite.sh:24      database="${KORPUS_BACKUP_SQLITE_PATH:-$root/var/korpus-ml.db}"
    scripts/build_reference_set.py   default=ROOT / "var/korpus-ml.db"
    scripts/corpus_release.py        default=ROOT / "var/korpus-ml.db"

Наслідок першої з трьох не гіпотетичний: `make backup-sqlite` виходить із rc=66
(«no database at …»), теки `var/backups/sqlite/` не існує, **бекапу живого корпусу на
276 МБ не робиться жодного разу**. Runbook при цьому каже про ті самі команди «These
commands are executable as written».

Найважливіше — що ця вада ВЖЕ стріляла і вже полагоджена. `scripts/serve_public.sh:170`
несе про неї коментар: «a previous deployment silently selected the empty
var/korpus-ml.db instead». Полагодили КОПІЮ, ЩО ЗЛАМАЛАСЬ, а не константу; три сестри
з тим самим хибним шляхом лишились стояти, і одна з них — бекап.

ЧОМУ САМЕ ДЕФОЛТИ, А НЕ ВСІ ОГОЛОШЕННЯ. Перша версія цього гейта вимагала, щоб шлях
до корпусу був у дереві ОДИН. Вимір її спростував за хвилину: баз законно кілька —
еталон живучості `var/liveness-fixture/korpus.db`, доктринальна `var/korpus-doctrine.db`,
обслуговуваний корпус. Правило «одне оголошення» дало б хибну тривогу на здоровому
дереві, а перевірка, чиї знахідки доводиться перебирати, гірша за відсутню.

Судиться вужчий і точніший клас: ДЕФОЛТ — те, що станеться, коли оператор не сказав
нічого. `default=` в argparse, `${VAR:-шлях}` в оболонці, `VAR ?= шлях` у Makefile.
Дефолт, який не існує, означає, що безаргументна дорога інструмента МЕРТВА, і виявиться
це в найгіршу мить. Конфіг і константа тесту дефолтами не є: там шлях подають свідомо.

ЧОМУ ПІДТВЕРДЖЕННЯ, А НЕ ІСНУВАННЯ НА ДИСКУ. Друга версія цього гейта питала диск, і
власна отрута живучості її спростувала за один прогін: проба копіює дерево БЕЗ `var/`,
тож у копії не існує жодної бази — гейт червонів би однаково в чистому клоні, у CI і в
продакшенному образі. Це рівно той клас, що вже стріляв: та сама функція на тому самому
дереві дає різний вирок, бо оточення інше.

Крім того, диск і не є перевіркою по суті. Журнал вироків від 30.08.2026 каже про той
самий `korpus-ml.db`: «лишився ПОРОЖНІМ (4 КБ), тобто не міряв нічого». Дефолт на
порожню базу мертвий рівно так само, як на відсутню, а існування їх не розрізняє —
неправильне значення не відрізняється від відсутнього.

Тому судиться ДЖЕРЕЛО: дефолт мусить бути ПІДТВЕРДЖЕНИЙ — названий бодай одним місцем,
яке саме дефолтом не є (значення в конфізі, константа в тесті, звичайне присвоєння в
модулі). Дефолт, у який не вірить ніхто, крім нього самого, — сирота. Виміряно: у
`var/korpus-ml.db` підтверджень НУЛЬ при трьох дефолтах, у обслуговуваного корпусу —
дев'ятнадцять. Реєстр правильних шляхів був би двадцять третім оголошенням, а гейт,
який читає власне оголошення, зелений рівно в тому стані, заради якого існує.

Порожня множина дефолтів — UNKNOWN, не PASS: «нічого не знайшов» частіше означає
зламаний пошук, ніж чисте дерево.

ЧИТАЮТЬСЯ ЛИШЕ ВИКОНУВАНІ ПОЗИЦІЇ. Коментар, докстрінг чи причина в реєстрі можуть
законно називати старий шлях — вони описують минуле, а не задають поведінку. Тому для
Python береться РОЗБІР ДЕРЕВА (присвоєння і `default=`), для оболонки — присвоєння поза
коментарем, для Makefile — `VAR ?= …`, для JSON — значення ключів `path`/`database`.
Рядок у докстрінгу не є оголошенням, і плутати їх означало б ловити прозу замість вади.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: Форма шляху до сховища корпусу — бази АБО теки об'єктів. Навмисно ширша за поточне
#: ім'я випуску: гейт мусить побачити РОЗХОДЖЕННЯ, а не підтвердити знайому константу.
#: Теку об'єктів додано 02.09.2026, коли перша версія форми пропустила
#: `KORPUS_BACKUP_OBJECT_ROOT:-$root/var/objects-ml` — другу ваду того самого класу в
#: тому самому файлі, за два рядки від першої.
_SHAPE = re.compile(r"^var/[\w./-]*(korpus[\w.-]*\.db|objects[\w.-]*)$")

_SKIP = ("apps/api/.venv/", "var/", "node_modules/", ".git/", "dist/")


def _relevant(text: str) -> bool:
    return bool(_SHAPE.match(text.strip()))


def _from_python(source: str) -> set[str]:
    """Лише `default=`. Докстрінг, коментар і звичайна константа дефолтом не є."""
    found: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover - файл не парситься
        return found

    def literals(node: ast.AST) -> list[str]:
        return [
            n.value
            for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ]

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg == "default":
                found.update(v for v in literals(keyword.value) if _relevant(v))
    return found


def _from_shell(source: str) -> set[str]:
    """Лише підстановка дефолта `${VAR:-шлях}` поза коментарем."""
    found: set[str] = set()
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for candidate in re.findall(
            r"\$\{[A-Za-z_][A-Za-z_0-9]*:-[^}]*?(var/[\w./-]*korpus[\w.-]*\.db)\}", stripped
        ):
            if _relevant(candidate):
                found.add(candidate)
    return found


def _from_makefile(source: str) -> set[str]:
    found: set[str] = set()
    for line in source.splitlines():
        if line.startswith("#"):
            continue
        match = re.match(r"^[A-Z_][A-Z_0-9]*\s*\?=\s*(\S+)", line)
        if match and _relevant(match.group(1)):
            found.add(match.group(1))
    return found


def _json_strings(payload: Any) -> list[str]:
    """Усі рядки JSON-документа, хоч би як глибоко вони лежали."""
    if isinstance(payload, dict):
        return [item for value in payload.values() for item in _json_strings(value)]
    if isinstance(payload, list):
        return [item for value in payload for item in _json_strings(value)]
    return [payload] if isinstance(payload, str) else []


def _assigned_strings(source: str) -> list[str]:
    """Рядки у ЗВИЧАЙНИХ присвоєннях. Дефолт argparse сюди не належить."""
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover - файл не парситься
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        found.extend(
            inner.value
            for inner in ast.walk(node.value)
            if isinstance(inner, ast.Constant) and isinstance(inner.value, str)
        )
    return found


def _corroborations(root: Path = ROOT) -> dict[str, list[str]]:
    """Місця, що називають шлях, НЕ будучи дефолтом: конфіг або звичайне присвоєння."""
    found: dict[str, list[str]] = {}
    for candidate in _readable(root, (".py", ".json")):
        source = candidate.read_text(encoding="utf-8")
        if candidate.suffix == ".json":
            try:
                strings = _json_strings(json.loads(source))
            except json.JSONDecodeError:
                continue
        else:
            strings = _assigned_strings(source)
        for text in strings:
            if _relevant(text):
                found.setdefault(text, []).append(str(candidate.relative_to(root)))
    return found


def _readable(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    """Файли дерева потрібних розширень, які справді читаються."""
    files: list[Path] = []
    for candidate in sorted(root.rglob("*")):
        if not candidate.is_file():
            continue
        relative = str(candidate.relative_to(root))
        wanted = candidate.suffix in suffixes or (candidate.name == "Makefile" and "" in suffixes)
        if relative.startswith(_SKIP) or not wanted:
            continue
        try:
            candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        files.append(candidate)
    return files


def observe(root: Path = ROOT) -> dict[str, list[str]]:
    """Хто оголошує ДЕФОЛТ. Ключ — шлях, значення — місця, що його називають."""
    declarations: dict[str, list[str]] = {}
    readers = {".py": _from_python, ".sh": _from_shell, "": _from_makefile}
    for candidate in _readable(root, (".py", ".sh", "")):
        key = candidate.suffix if candidate.name != "Makefile" else ""
        for item in readers[key](candidate.read_text(encoding="utf-8")):
            declarations.setdefault(item, []).append(str(candidate.relative_to(root)))
    return declarations


def assess(
    declarations: dict[str, list[str]], corroborations: dict[str, list[str]] | None = None
) -> dict[str, Any]:
    if not declarations:
        return {
            "status": "UNKNOWN",
            "corroborations": {},
            "declarations": {},
            "problems": ["жодного дефолта не знайдено — це зламаний пошук, не чисте дерево"],
        }
    support = corroborations or {}
    problems = []
    for path, places in sorted(declarations.items()):
        backing = [w for w in support.get(path, []) if w not in places]
        if not backing:
            problems.append(
                f"дефолт {path} не підтверджений НІКИМ, крім себе: {', '.join(sorted(places))}. "
                "Шлях, у який не вірять ні конфіг, ні тест, ні інший модуль, — сирота, і "
                "безаргументна дорога веде в нікуди"
            )
    return {
        "status": "FAIL" if problems else "PASS",
        "corroborations": {p: sorted(w) for p, w in sorted(support.items())},
        "declarations": {p: sorted(w) for p, w in sorted(declarations.items())},
        "problems": problems,
    }


def _selftest() -> int:
    # Шляхи зібрані склеюванням навмисно: дослівний рядок у цьому файлі став би
    # двадцять третім оголошенням, і гейт міряв би сам себе.
    orphan = "var/" + "runtime/x/korpus.db"
    cases = [
        ({}, None, "UNKNOWN", "порожня множина не є PASS"),
        ({orphan: ["a.py"]}, None, "FAIL", "дефолт без підтвердження — сирота"),
        ({orphan: ["a.py"]}, {orphan: ["a.py"]}, "FAIL", "сам себе не підтверджує"),
        ({orphan: ["a.py"]}, {orphan: ["config/x.json"]}, "PASS", "підтверджений конфігом"),
    ]
    for declarations, support, expected, label in cases:
        got = assess(declarations, support)["status"]
        if got != expected:
            print(json.dumps({"selftest": "FAIL", "case": label, "got": got}, ensure_ascii=False))
            return 1
    # Присвоєння — оголошення; докстрінг — ні.
    sample = "var/" + "runtime/a/korpus.db"
    if _from_python(f'p(default="{sample}")') != {sample}:
        print(
            json.dumps(
                {"selftest": "FAIL", "case": "дефолт argparse не побачений"}, ensure_ascii=False
            )
        )
        return 1
    if _from_python(f'DB = "{sample}"') != set():
        print(
            json.dumps(
                {"selftest": "FAIL", "case": "звичайна константа зарахована як дефолт"},
                ensure_ascii=False,
            )
        )
        return 1
    if _from_python(f'"""див. {sample}"""') != set():
        print(json.dumps({"selftest": "FAIL", "case": "докстрінг зарахований"}, ensure_ascii=False))
        return 1
    if _from_shell(f"# старий {sample}") != set():
        print(
            json.dumps(
                {"selftest": "FAIL", "case": "коментар оболонки зарахований"}, ensure_ascii=False
            )
        )
        return 1
    if _from_shell('x="${V:-' + sample + '}"') != {sample}:
        print(
            json.dumps(
                {"selftest": "FAIL", "case": "дефолт оболонки не побачений"}, ensure_ascii=False
            )
        )
        return 1
    print(json.dumps({"selftest": "PASS"}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    report = assess(observe(), _corroborations(ROOT))
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
