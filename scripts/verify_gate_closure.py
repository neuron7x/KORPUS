#!/usr/bin/env python3
"""Що саме означає «дерево зелене».

Виміряно 31.08.2026 на цьому Makefile: **193 цілі, з них 39 досяжні з `check`**;
перевірочних цілей — 44, і **31 із них недосяжна ні з `check`, ні з `validate`**.
Серед недосяжних: `audit-verify`, `span-hygiene`, `runtime-corpus-audit`,
`gate-liveness`, `determinism-gate`, `coverage-ratchet`, `provenance-verify`,
`verify-clean-clone`, `mutation-probe`. Три з них того ж дня перевірили руками —
усі три червоні.

Тобто речення «`make check` зелений» було твердженням про підмножину, якої ніхто
не перелічив, і розмір підмножини ніде не був записаний. Це не борг окремих
цілей — це те, що САМЕ СЛОВО «зелено» не мало означення.

Гейт дає йому означення й робить його виконуваним:

    кожна перевірочна ціль АБО досяжна з `check`,
    АБО названа в реєстрі — з причиною і датою.

Три речі, яких він НЕ пробачає, і кожна з них — окремий спосіб збрехати:

  ВІДСУТНІЙ ВИНЯТОК   нова перевірочна ціль, яку ніхто не підключив і ніхто не
                      назвав. Саме так з'явилась 31 попередня: жодна не була
                      рішенням, усі були тишею.
  МЕРТВИЙ ВИНЯТОК     запис про ціль, яка НАСПРАВДІ досяжна. Він каже читачеві,
                      що діри немає там, де її вже немає, — і привчає не вірити
                      реєстру. Мертвий виняток бреше не менше за відсутній.
  ПРИМАРНИЙ ВИНЯТОК   запис про ціль, якої в Makefile більше немає. Реєстр, що
                      накопичує привидів, з часом описує інший файл.

⚠ Пастка в самому парсері, і вона тієї ж форми, що й усе інше сьогодні. Ребро
графа — це не лише залежність у заголовку правила: `evidence-refresh` викликає
`$(MAKE) dependency-locks` у РЕЦЕПТІ. Парсер, що читає лише заголовки, оголосив
би `dependency-locks` недосяжною й вимагав би для неї виправдання, якого не
треба. Тобто перевірка досяжності, зроблена наївно, сама стає джерелом хибних
дір. Рецепти читаються (`_recipe_edges`), і на це є негативний контроль.

    verify_gate_closure.py
    verify_gate_closure.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"
REGISTRY = ROOT / "config/operations/gate-closure.json"
SCHEMA = "korpus.gate-closure.v1"

#: Корені, з яких рахується досяжність.
#:
#: `check` — те, що людина запускає перед злиттям; `validate` входить у нього, але
#: названий окремо, бо саме його запускають частіше й саме про нього кажуть «зелений».
#:
#: `check-deployment` — другий вхід, і без нього цей гейт сам був би неправдою. Частина
#: перевірок міряє не дерево, а РОЗГОРТАННЯ: обслуговуваний корпус, його журнал, його
#: прольоти. Вони не можуть стояти в `check`, бо той мусить проходити там, де корпусу
#: немає, — і поки другого входу не існувало, вони не мали де жити взагалі. Рахувати їх
#: «дірами» було так само хибно, як рахувати «закритими»: у них не було лану.
#: `check-nightly` — третій вхід: дороге за побудовою. Копіює дерево або переганяє
#: повний набір, тому не належить у прогін перед злиттям; але «не належить туди» і «не
#: бігає ніде» — різні речі, і без власного лану це була друга.
ROOTS = ("check", "validate", "check-deployment", "check-nightly")

#: Що вважається ПЕРЕВІРОЧНОЮ ціллю. Правило за іменем, і воно свідомо широке:
#: хибно віднесена сюди неперевірочна ціль коштує одного запису в реєстрі з
#: причиною, а пропущена перевірочна коштує мовчазної діри. Ціна асиметрична,
#: тому й поріг асиметричний.
VERIFICATION = re.compile(
    r"verify|check|audit|gate|lint|hygiene|ratchet|integrity|liveness|validate|probe"
    r"|axes|stores|selftest"
)

#: Заголовок правила. `:=` виключено — це присвоєння змінної, не ціль.
_RULE = re.compile(
    r"^(?P<names>[A-Za-z0-9._%/-]+(?:\s+[A-Za-z0-9._%/-]+)*)\s*:(?!=)\s*(?P<deps>.*)$"
)
_RECURSIVE_MAKE = re.compile(r"\$\(MAKE\)\s+([A-Za-z0-9._-]+)")
#: Скрипт, який рецепт справді запускає. Досяжність ЦІЛІ — не те саме, що виконання
#: перевірки: `validate` кличе `scripts/validate_infrastructure.py` і
#: `scripts/validate_kubernetes.py` прямо в рецепті, а цілі `infra-validate` і
#: `kubernetes-validate` роблять рівно те саме. Перевірка, що дивиться лише на граф
#: цілей, оголосила б їх дірами — і зажадала б виправдання для того, що вже
#: виконується. Тому одиниця обліку тут — СКРИПТ, а ціль лише його носій.
_SCRIPT = re.compile(r"(scripts/[A-Za-z0-9_./-]+\.(?:py|sh))")


# ------------------------------------------------------------------- граф (без I/O)


#: Аргументи, про які ДОВЕДЕНО, що вони не міняють предмет перевірки: куди покласти звіт
#: і від якого кореня рахувати шляхи. Усе інше семантичне за замовчуванням.
#:
#: Правило перевернуте навмисно. Перша редакція мала БІЛИЙ СПИСОК семантичних прапорців
#: (`--require|--strict|--full|--deep|--bound|--exact`), і рецензія слушно показала, що
#: він пропускає `--mode unsafe`, `--backend postgres`, `--threshold 100`: усе, чого
#: автор списку не передбачив, мовчки ставало несемантичним. Список ВИНЯТКІВ помиляється
#: у безпечний бік — незнайомий аргумент робить цілі різними, і найгірше, що станеться,
#: це зайвий запис у реєстрі прогалин.
_NON_SEMANTIC = frozenset(
    {"--out", "--output", "--root", "--report", "--outfile", "--osv-out", "--json"}
)

#: Змінні оточення, які має кожен рецепт і які нічого не кажуть про предмет.
_AMBIENT_ENV = frozenset({"PYTHONPATH", "PYTHON", "PY", "MAKEFLAGS"})

_ENV_ASSIGNMENT = re.compile(r"^(?P<name>[A-Z][A-Z0-9_]*)=")

#: `$(VAR)`, `${VAR}`, `$$(cat …)` — предмет, поданий у момент виклику.
_SUBSTITUTION = re.compile(r"\$+[({][^)}]*[)}]")

#: Перенаправлення оболонки: `> var/x.json`, `2>/dev/null`, `>> лог`. Куди ллється
#: stdout — не предмет перевірки, так само як `--out`. Виміряно 03.09.2026 дзеркалом
#: CI: `model_check_assurance.py > var/…` у Makefile і той самий скрипт без
#: перенаправлення в CI рахувались РІЗНИМИ командами через оформлення виводу.
_REDIRECT = re.compile(r"\s\d?>>?\s*\S+")


def normalise_invocation(script: str, tail: str) -> str:
    """Канонічна тотожність запуску: скрипт + усе, що міняє його предмет.

    Раніше тотожністю було саме лише ім'я файла, і `enforced` зараховував ціль
    виконаною, щойно той самий файл запускав хтось досяжний. Виміряно 02.09.2026:
    `handoff-verify` і `handoff-verify-bound` запускають один
    `verify_handoff_contract.py`, і вся різниця між ними — `--require-bound`, тобто
    САМЕ ТОЙ предикат, заради якого друга ціль існує.

    Тепер зберігається кожен аргумент, крім названих у `_NON_SEMANTIC`: два запуски, що
    пишуть у різні файли, перевіряють одне й те саме, і розрізняти їх означало б
    наплодити «непокритих» цілей там, де покриття є. Значення після такого прапорця
    відкидається разом із ним.

    Порядок аргументів нормалізується сортуванням: `--a --b` і `--b --a` — та сама
    команда, і залишати їх різними означало б, що тотожність залежить від набору тексту.
    """
    # Підстановки вирізаються ЦІЛКОМ, до розбиття на токени: `$$(cat dist/LATEST)` — це
    # три токени, і фільтр «токен починається з $» лишав би хвіст `dist/LATEST)`, тобто
    # робив би дві цілі різними через оформлення підстановки, а не через предмет.
    # `$(if $(OUT),--out "$(OUT)")` — вкладені дужки. Регулярний вираз підстановки
    # спиняється на ПЕРШІЙ `)` і лишав хвіст `,--out "$(OUT)")` як «аргументи». Усе під
    # `$(if …)` / `$(or …)` необов'язкове за побудовою і предметом бути не може, тож
    # спершу прибирається воно (з рахунком дужок), а вже потім прості підстановки.
    tokens = _SUBSTITUTION.sub(" ", _REDIRECT.sub(" ", _strip_optional(tail))).split()
    kept: list[str] = []
    skip = False
    for token in tokens:
        if skip:
            skip = False
            continue
        if token in _NON_SEMANTIC:
            skip = True
            continue
        if any(token.startswith(flag + "=") for flag in _NON_SEMANTIC):
            continue
        bare = token.strip("\"'")
        # Змінна чи підстановка команди — це ПРЕДМЕТ, поданий у момент виклику, а не
        # предикат. `zip-safety-verify` бере `"$(ARCHIVE)"`, а `package` — архів, який
        # сам щойно зібрав; перевірка на zip-slip від цього не міняється, міняється лише
        # те, ЩО перевіряють. Цілі, які потребують аргументу, вже має клас
        # `requires_argument` у реєстрі, і дублювати його тотожністю команди означало б
        # оголосити непокритим те, що покрите.
        #
        # Лапки знімаються ДО перевірки: перша редакція дивилась на `token[0]`, а токен
        # у рецепті виглядає як `"$(ARCHIVE)"` — починається з лапки, і фільтр змінних
        # його не бачив. Спіймано тестом `test_zip_safety_is_no_longer_an_accepted_gap`,
        # який стеріг рішення, ухвалене раніше й правильно.
        if bare.startswith("$") or bare in {"\\", "&&", "||", ";", "|"} or not bare:
            continue
        kept.append(bare)
    return " ".join([script, *sorted(kept)]) if kept else script


def _invocation(line: str, match: re.Match[str]) -> str:
    """Тотожність запуску, взята з рядка рецепта: скрипт плюс його значущі аргументи."""
    tail = line[match.end() :]
    # Наступна команда в тому самому рядку — це вже інший запуск.
    for separator in ("&&", "||", ";", "|"):
        index = tail.find(separator)
        if index >= 0:
            tail = tail[:index]
    return normalise_invocation(match.group(1), tail)


def invocations(line: str) -> list[str]:
    """Усі канонічні тотожності запусків у рядку — рецепта make чи скрипта CI.

    Публічна форма `_invocation`, бо ту саму тотожність мусить рахувати дзеркало CI
    (`verify_ci_mirror.py`): два обчислення однієї тотожності розійшлись би мовчки.
    """
    return [_invocation(line, match) for match in _SCRIPT.finditer(line)]


def parse_graph(text: str) -> tuple[dict[str, set[str]], list[str], dict[str, set[str]]]:
    """Ціль → її передумови, ребра з рецептів, і скрипти, які ціль запускає.

    Повертає (ребра, оголошені цілі, скрипти на ціль). Порядок оголошення
    зберігається, бо звіт, чий вміст залежить від планування, не можна порівняти
    між прогонами.
    """
    edges: dict[str, set[str]] = {}
    scripts: dict[str, set[str]] = {}
    declared: list[str] = []
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("\t"):
            if current is not None:
                for match in _RECURSIVE_MAKE.finditer(line):
                    edges.setdefault(current, set()).add(match.group(1))
                for match in _SCRIPT.finditer(line):
                    scripts.setdefault(current, set()).add(_invocation(line, match))
            continue
        matched = _RULE.match(line)
        if matched is None:
            continue
        names = matched.group("names").split()
        if names[0] == ".PHONY":
            current = None
            continue
        # Змінні в передумовах (`$(if ...)`) не є цілями і не можуть бути ребрами.
        dependencies = {d for d in matched.group("deps").split() if not d.startswith("$")}
        for name in names:
            if name not in edges:
                declared.append(name)
            edges.setdefault(name, set()).update(dependencies)
        current = names[0]
    return edges, declared, scripts


#: Змінні, які завжди має збірка; їхня згадка в рецепті нічого не вимагає від людини.
_AMBIENT = frozenset({"PY", "PYTHON", "MAKE", "SHELL", "CURDIR", "SERVED_CORPUS", "OBJECTS"})
_VARIABLE = re.compile(r"\$\((?P<name>[A-Z][A-Z0-9_]*)\)")
_GUARD = re.compile(r"test\s+-n\s+\"?\$\((?P<name>[A-Z][A-Z0-9_]*)\)")


def recipes(text: str) -> dict[str, list[str]]:
    """Ціль → рядки її рецепта. Порядок збережено; заголовки не входять."""
    found: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("\t"):
            if current is not None:
                found.setdefault(current, []).append(line)
            continue
        matched = _RULE.match(line)
        if matched is None:
            continue
        names = matched.group("names").split()
        current = None if names[0] == ".PHONY" else names[0]
    return found


def phantom_targets(text: str) -> list[str]:
    """Імена, оголошені в `.PHONY`, для яких правила немає взагалі.

    `make <ім'я>` для такого імені виходить із НУЛЕМ, не виконавши нічого: GNU make
    вважає phony-ціль без рецепта досягнутою. Тобто ім'я, яке обіцяє перевірку, ніколи
    не буває червоним — сигнал із нульовою ентропією.

    Виміряно 04.09.2026: `quality-gate` стояв у `.PHONY` від першого коміту, рецепта не
    мав ЖОДНОГО разу за всю історію, і жоден рецепт, конвеєр чи скрипт на нього не
    посилався. `make quality-gate` казав «Ціль не вимагає виконання команд» і rc=0.

    Реєстр закриття цього не бачив за побудовою: розбір Makefile пропускає рядок
    `.PHONY` (там імена стоять у передумовах, не в цілях), тож примарне ім'я не
    потрапляло навіть у перелік оголошених — його не можна було ні покрити, ні
    внести до винятків. Дірка була рівно там, де перевірка не дивилась.
    """
    phony: set[str] = set()
    with_rule: set[str] = set()
    for line in text.splitlines():
        if line.startswith("\t"):
            continue
        matched = _RULE.match(line)
        if matched is None:
            continue
        names = matched.group("names").split()
        if names[0] == ".PHONY":
            phony.update(matched.group("deps").split())
            continue
        with_rule.update(name for name in names if "%" not in name)
    return sorted(phony - with_rule)


def duplicate_recipes(text: str) -> list[str]:
    """Цілі, оголошені двічі З РЕЦЕПТОМ. GNU make лишає ОСТАННІЙ і лише попереджає.

    Це та сама форма, що вже коштувала нам зеленого конвеєра: дубльоване ім'я джоба
    в `include` перекривається МОВЧКИ. Тут виміряно 01.09.2026 — `fetch-stubs` мав два
    визначення, і те, що виконувалось, вийшло сильнішим ВИПАДКОВО: у порядку навпаки
    ціль ходила б без `--database`, тобто не дивилась би на обслуговуваний корпус і
    лишалась зеленою. Попередження make ніхто не читає, бо воно не змінює коду виходу.
    """
    with_recipe: Counter[str] = Counter()
    current: str | None = None
    counted: set[str] = set()
    for line in text.splitlines():
        if line.startswith("\t"):
            if current is not None and current not in counted and line.strip():
                with_recipe[current] += 1
                counted.add(current)
            continue
        matched = _RULE.match(line)
        if matched is None:
            continue
        names = matched.group("names").split()
        if names[0] == ".PHONY" or "%" in names[0]:
            current = None
            continue
        current = names[0]
        counted.discard(current)
    return sorted(name for name, count in with_recipe.items() if count > 1)


def _strip_optional(line: str) -> str:
    """Прибрати `$(if ...)` і `$(or ...)` разом із їхнім вмістом, рахуючи дужки.

    Усе, що всередині них, за побудовою НЕ обов'язкове: `$(if $(POLICY),--policy ...)`
    зникає цілком, коли POLICY порожня, а `$(or $(A),$(B))` має запасне значення.
    """
    for opener in ("$(if ", "$(or "):
        while (start := line.find(opener)) >= 0:
            end = _closing_paren(line, start)
            if end is None:
                return line[:start]
            line = line[:start] + line[end + 1 :]
    return line


def _closing_paren(text: str, start: int) -> int | None:
    """Індекс дужки, що закриває відкриту одразу після `start`, або None.

    Винесено з `_strip_optional` не заради краси: разом вони давали глибину шість,
    а ратчет складності ходить УНИЗ. Незакрита дужка — не помилка розбору, а обірваний
    рядок продовження; тоді все від `start` вважається необов'язковим.
    """
    depth = 0
    for index in range(start + 1, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return None


def mandatory_variables(recipe: list[str]) -> set[str]:
    """Змінні, без яких ціль СПРАВДІ не працює: під `test -n` або згадані безумовно."""
    required: set[str] = set()
    for line in recipe:
        for match in _GUARD.finditer(line):
            required.add(match.group("name"))
        for match in _VARIABLE.finditer(_strip_optional(line)):
            required.add(match.group("name"))
    return required - _AMBIENT


def reachable(edges: dict[str, set[str]], roots: tuple[str, ...]) -> set[str]:
    """Транзитивне замикання від коренів. Цикли не зациклюють: `seen` росте."""
    seen: set[str] = set()
    queue = deque(root for root in roots if root in edges)
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        queue.extend(edges.get(node, ()))
    return seen


def selftest_only(makefile: str) -> set[str]:
    """Цілі, чий рецепт не робить нічого, крім запуску `--selftest`.

    Їхню роботу виконує `selftest-coverage`, який знаходить кожен скрипт з оголошенням
    прапорця і запускає його сам. Але побачити це через перелік скриптів у рецепті
    неможливо: у `selftest-coverage` в рецепті лише ВІН САМ, бо переліку в ньому немає
    навмисно — перелік був би другим оголошенням того самого факту.

    Тому правило записане тут, а не в реєстрі. Виняток у реєстрі був би твердженням,
    яке ніхто не переміряє; це — обчислення, яке хибніє разом із рецептом.
    """
    covered: set[str] = set()
    for target, recipe in recipes(makefile).items():
        lines = [line for line in recipe if line.strip() and not line.strip().startswith("#")]
        if lines and all("--selftest" in line for line in lines):
            covered.add(target)
    return covered


def verification_targets(declared: list[str]) -> list[str]:
    return [name for name in declared if VERIFICATION.search(name)]


# ---------------------------------------------------------------- судження (без I/O)


def _finding(check: str, verdict: str, detail: str) -> dict[str, str]:
    return {"check": check, "verdict": verdict, "detail": detail}


def _named(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = registry.get("accepted") if isinstance(registry, dict) else None
    if not isinstance(entries, list):
        return {}
    return {
        entry["target"]: entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("target"), str)
    }


def enforced(
    edges: dict[str, set[str]],
    scripts: dict[str, set[str]],
    roots: tuple[str, ...] = ROOTS,
) -> set[str]:
    """Цілі, чия робота СПРАВДІ виконується під `check`.

    Ціль виконується, якщо вона досяжна графом АБО якщо кожен скрипт, який вона
    запускає, запускає ще й хтось досяжний. Друга умова — не поблажка: `validate`
    виконує ті самі два валідатори інфраструктури, що й `infra-validate`, і
    вимагати для них запису в реєстрі означало б назвати дірою те, що закрите.
    """
    covered = reachable(edges, roots)
    running: set[str] = set()
    for target in covered:
        running |= scripts.get(target, set())
    result = set(covered)
    for target, used in scripts.items():
        if used and used <= running:
            result.add(target)
    return result


def assess(
    edges: dict[str, set[str]],
    declared: list[str],
    registry: dict[str, Any],
    scripts: dict[str, set[str]] | None = None,
    makefile: str | None = None,
) -> list[dict[str, str]]:
    """Вирок над графом і реєстром. UNKNOWN — окремо і НЕ PASS."""
    if not declared:
        return [_finding("gate_closure", "UNKNOWN", "Makefile не розібрано: цілей нуль")]
    if not any(root in edges for root in ROOTS):
        return [
            _finding("gate_closure", "UNKNOWN", "жодного кореня " + ", ".join(ROOTS) + " немає")
        ]

    if makefile is None:
        # Без тексту Makefile покриття не обчислюється ПОВНІСТЮ: знижку для цілей, чия
        # робота — самоперевірка, дає `selftest_only`, і без неї вони виглядали б дірами.
        # Оголосити їх дірами означало б звинуватити за брак ВЛАСНОГО входу, тому тут
        # UNKNOWN, а не FAIL: невиміряне не є ні провалом, ні дозволом.
        return [_finding("gate_closure", "UNKNOWN", "Makefile не переданий — покриття не виміряно")]

    covered = enforced(edges, scripts or {})
    if "selftest-coverage" in covered:
        covered |= selftest_only(makefile)
    named = _named(registry)
    targets = verification_targets(declared)
    findings: list[dict[str, str]] = []

    missing = sorted(t for t in targets if t not in covered and t not in named)
    findings.append(
        _finding(
            "unregistered_gap",
            "FAIL",
            "перевірочна ціль ні під гейтом, ні в реєстрі: " + ", ".join(missing),
        )
        if missing
        else _finding("unregistered_gap", "PASS", f"{len(targets)} перевірочних цілей враховано")
    )

    dead = sorted(t for t in named if t in covered)
    findings.append(
        _finding(
            "dead_exemption", "FAIL", "виняток для цілі, яка вже під гейтом: " + ", ".join(dead)
        )
        if dead
        else _finding("dead_exemption", "PASS", f"{len(named)} записів реєстру всі ще потрібні")
    )

    ghosts = sorted(t for t in named if t not in edges)
    findings.append(
        _finding(
            "ghost_exemption",
            "FAIL",
            "виняток для цілі, якої немає в Makefile: " + ", ".join(ghosts),
        )
        if ghosts
        else _finding("ghost_exemption", "PASS", "жодного запису про неіснуючу ціль")
    )

    unreasoned = sorted(
        target
        for target, entry in named.items()
        if not isinstance(entry.get("reason"), str) or len(entry["reason"].strip()) < 20
    )
    findings.append(
        _finding(
            "unreasoned_exemption",
            "FAIL",
            "запис без причини (≥20 символів): " + ", ".join(unreasoned),
        )
        if unreasoned
        else _finding("unreasoned_exemption", "PASS", "кожен запис несе причину")
    )

    findings.extend(_assess_makefile_truth(named, makefile))
    return findings


def _assess_makefile_truth(
    named: dict[str, dict[str, Any]], makefile: str | None
) -> list[dict[str, str]]:
    """Дві властивості САМОГО Makefile, які реєстр припускає, але ніхто не міряв.

    Перша: жодна ціль не оголошена двічі з рецептом — інакше make мовчки лишає
    останній, і те, що виконується, залежить від порядку рядків, а не від наміру.

    Друга: причина у реєстрі — теж ТВЕРДЖЕННЯ, і його ніхто не перевіряв. Запис класу
    `requires_argument` каже «без аргументу не запуститься»; це можна спростувати
    статично — якщо в рецепті кожна змінна загорнута в `$(if ...)`, ціль запускається
    порожньою, і виняток описує неіснуючу перешкоду.
    """
    if makefile is None:
        return [
            _finding("duplicate_target", "UNKNOWN", "Makefile не переданий — не виміряно"),
            _finding("unfounded_requirement", "UNKNOWN", "Makefile не переданий — не виміряно"),
            _finding("phantom_target", "UNKNOWN", "Makefile не переданий — не виміряно"),
        ]

    duplicates = duplicate_recipes(makefile)
    found = [
        _finding(
            "duplicate_target",
            "FAIL",
            "ціль оголошена двічі з рецептом, make мовчки лишає останній: " + ", ".join(duplicates),
        )
        if duplicates
        else _finding("duplicate_target", "PASS", "жодної цілі з двома рецептами")
    ]

    all_recipes = recipes(makefile)
    unfounded = sorted(
        target
        for target, entry in named.items()
        if entry.get("class") == "requires_argument"
        and not mandatory_variables(all_recipes.get(target, []))
    )
    found.append(
        _finding(
            "unfounded_requirement",
            "FAIL",
            "виняток «потребує аргумент» для цілі, яка запускається без нього: "
            + ", ".join(unfounded),
        )
        if unfounded
        else _finding("unfounded_requirement", "PASS", "кожне «потребує аргумент» має підставу")
    )

    phantoms = phantom_targets(makefile)
    found.append(
        _finding(
            "phantom_target",
            "FAIL",
            "ім'я в .PHONY без правила: make виходить нулем, не зробивши нічого: "
            + ", ".join(phantoms),
        )
        if phantoms
        else _finding("phantom_target", "PASS", "кожне ім'я в .PHONY має правило")
    )
    return found


def verdict(findings: list[dict[str, str]]) -> str:
    if not findings:
        return "UNKNOWN"
    verdicts = {finding["verdict"] for finding in findings}
    if "FAIL" in verdicts:
        return "FAIL"
    return "UNKNOWN" if "UNKNOWN" in verdicts else "PASS"


# ------------------------------------------------------------------ негативні контролі


#: Скільки пар звіряє `_identity_selftest`. Підсумок, який не рахує власних випадків,
#: звітує про менше, ніж перевіряє.
_IDENTITY_CASES = 10


def _identity_selftest() -> list[str]:
    """Отрути для КАНОНІЧНОЇ тотожності запуску.

    Рецензія 03.09.2026 показала, що білий список семантичних прапорців пропускає все,
    чого автор списку не передбачив. Ці твердження існують, щоб заміна білого списку на
    список винятків не могла тихо звузитись назад.
    """
    problems: list[str] = []
    same_subject = [
        ("--out a.json", "--out b.json"),
        ("--a --b", "--b --a"),
        ("--a > var/x.json", "--a"),
        ('--a $(if $(OUT),--out "$(OUT)")', "--a"),
    ]
    other_subject = [
        ("--mode safe", "--mode unsafe"),
        ("--backend sqlite", "--backend postgres"),
        ("--threshold 0", "--threshold 100"),
        ("--require-bound", ""),
        ("--selftest", ""),
        ("verify", "sign"),
    ]
    for left, right in same_subject:
        if normalise_invocation("s.py", left) != normalise_invocation("s.py", right):
            problems.append(f"той самий предмет розділено: {left!r} проти {right!r}")
    for left, right in other_subject:
        if normalise_invocation("s.py", left) == normalise_invocation("s.py", right):
            problems.append(f"РІЗНІ предмети злито в один: {left!r} проти {right!r}")
    return problems


def selftest() -> int:
    """Кожен спосіб збрехати мусить червоніти ОКРЕМО, і чистий граф — зеленіти."""
    clean_make = (
        "check: validate span-hygiene\n\tone\n"
        "validate: audit-verify\n\ttwo\n"
        "span-hygiene:\n\tthree\n"
        "audit-verify:\n\tfour\n"
    )
    recipe_make = "check:\n\t$(MAKE) span-hygiene\nspan-hygiene:\n\techo\n"
    orphan_make = clean_make + "gate-liveness:\n\tfive\n"

    def run(makefile: str, registry: dict[str, Any]) -> str:
        edges, declared, scripts = parse_graph(makefile)
        return verdict(assess(edges, declared, registry, scripts, makefile))

    reason = "причина, довша за двадцять символів"
    cases: list[tuple[str, str, dict[str, Any], str]] = [
        ("усе під гейтом", clean_make, {"accepted": []}, "PASS"),
        (
            "ребро з РЕЦЕПТА рахується як досяжність",
            recipe_make,
            {"accepted": []},
            "PASS",
        ),
        ("нова ціль, яку ніхто не підключив і не назвав", orphan_make, {"accepted": []}, "FAIL"),
        (
            "названа — і тоді дозволено",
            orphan_make,
            {"accepted": [{"target": "gate-liveness", "reason": reason, "on": "2026-08-31"}]},
            "PASS",
        ),
        (
            "мертвий виняток: ціль уже під гейтом",
            clean_make,
            {"accepted": [{"target": "span-hygiene", "reason": reason, "on": "2026-08-31"}]},
            "FAIL",
        ),
        (
            "примарний виняток: цілі в Makefile немає",
            clean_make,
            {"accepted": [{"target": "no-such-target", "reason": reason, "on": "2026-08-31"}]},
            "FAIL",
        ),
        (
            "виняток без причини",
            orphan_make,
            {"accepted": [{"target": "gate-liveness", "reason": "бо", "on": "2026-08-31"}]},
            "FAIL",
        ),
        ("порожній Makefile — UNKNOWN, не PASS", "", {"accepted": []}, "UNKNOWN"),
        (
            "є цілі, але немає жодного кореня — UNKNOWN, не PASS",
            "span-hygiene:\n\tone\n",
            {"accepted": []},
            "UNKNOWN",
        ),
        ("реєстр не список — читається як порожній, не як дозвіл", orphan_make, {}, "FAIL"),
        (
            "ціль з двома рецептами: make мовчки лишить останній",
            clean_make + "span-hygiene:\n\tsix\n",
            {"accepted": []},
            "FAIL",
        ),
        (
            "другий заголовок БЕЗ рецепта — законний і не червоніє",
            clean_make + "span-hygiene: audit-verify\n",
            {"accepted": []},
            "PASS",
        ),
        (
            "ім'я в .PHONY без правила: make каже 0, не зробивши нічого",
            ".PHONY: quality-gate\n" + clean_make,
            {"accepted": []},
            "FAIL",
        ),
        (
            "усі імена .PHONY мають правила — законно",
            ".PHONY: span-hygiene audit-verify\n" + clean_make,
            {"accepted": []},
            "PASS",
        ),
        (
            "правило нижче за .PHONY — порядок рядків не робить ім'я примарою",
            ".PHONY: late-target\n" + clean_make + "late-target:\n\tseven\n",
            {"accepted": [{"target": "late-target", "reason": reason, "on": "2026-09-04"}]},
            "PASS",
        ),
        (
            "«потребує аргумент» для цілі, де кожна змінна необов'язкова",
            orphan_make,
            {
                "accepted": [
                    {
                        "target": "gate-liveness",
                        "class": "requires_argument",
                        "reason": reason,
                        "on": "2026-08-31",
                    }
                ]
            },
            "FAIL",
        ),
        (
            "«потребує аргумент» із безумовною змінною — підстава є",
            clean_make + 'gate-liveness:\n\t$(PY) x.py --in "$(LEDGER)"\n',
            {
                "accepted": [
                    {
                        "target": "gate-liveness",
                        "class": "requires_argument",
                        "reason": reason,
                        "on": "2026-08-31",
                    }
                ]
            },
            "PASS",
        ),
        (
            "змінна лише під $(if ...) підставою не є",
            clean_make + 'gate-liveness:\n\t$(PY) x.py $(if $(LEDGER),--in "$(LEDGER)")\n',
            {
                "accepted": [
                    {
                        "target": "gate-liveness",
                        "class": "requires_argument",
                        "reason": reason,
                        "on": "2026-08-31",
                    }
                ]
            },
            "FAIL",
        ),
    ]

    bad = 0
    for name, makefile, registry, expected in cases:
        got = run(makefile, registry)
        ok = got == expected
        bad += not ok
        print(f"  [{'ok' if ok else 'ЗБІЙ'}] {name}: {got}")
    identity = _identity_selftest()
    for problem in identity:
        print(f"  [ЗБІЙ] тотожність команди: {problem}")
    bad += len(identity)
    total = len(cases) + _IDENTITY_CASES
    print(f"\nнегативний контроль: {total - bad}/{total}")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--makefile", type=Path, default=MAKEFILE)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--out", type=Path, default=ROOT / "var/gate-closure.json")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()

    try:
        text = arguments.makefile.read_text(encoding="utf-8")
    except OSError as error:
        print(json.dumps({"schema": SCHEMA, "status": "UNKNOWN", "reason": str(error)}))
        return 2
    try:
        registry = json.loads(arguments.registry.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        registry = {}

    edges, declared, scripts = parse_graph(text)
    findings = assess(edges, declared, registry, scripts, text)
    overall = verdict(findings)
    covered = enforced(edges, scripts)
    targets = verification_targets(declared)
    report = {
        "schema": SCHEMA,
        "status": overall,
        "targets_declared": len(declared),
        "targets_reachable_from_check": len(covered & set(declared)),
        "verification_targets": len(targets),
        "accepted_gaps": len(_named(registry)),
        "findings": findings,
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for finding in findings:
        print(f"  [{finding['verdict']}] {finding['check']}: {finding['detail']}")
    print(f"\ngate-closure: {overall}  → {arguments.out}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
