r"""Скрипт, що вимагає аргумент, мусить його отримувати В КОЖНОМУ місці виклику.

Обов'язковий аргумент — це рішення: він існує саме тому, що мовчазний дефолт зробив би
доказ одного стану непомітно придатним для тверджень про інший. Але рішення живе в
argparse, а виклики розкидані по Makefile і `.gitlab-ci.yml`, і між ними немає жодного
зв'язку, крім уважності того, хто правив.

ВИМІРЯНО 02.09.2026. `run_exact_environment_gate.py` дістав `--profile` з
`required=True` і без дефолта. Makefile оновили в тому ж коміті — обидва виклики.
`.gitlab-ci.yml:642` лишився без аргументу:

    python scripts/run_exact_environment_gate.py
    -> error: the following arguments are required: --profile
    -> rc=2

Це не косметика: крок стоїть у джобі `source:package`, від якої залежать
`production:release` і `gcp:deploy-production`. Реліз падав би на кроці, доданому заради
того, щоб реліз був доведений.

Розбір СТАТИЧНИЙ. Імпортувати скрипт заради його парсера означало б виконати його
верхній рівень — а там `sys.path`, читання конфігів і робота з базою.

ОБСЯГ НАЗВАНИЙ, бо перша версія цієї перевірки кричала вовк. Вона дала 19 знахідок,
із яких справжніх було ДВІ. Решта — два класи хибних спрацювань:

  * перенос рядка. `... run_exact_environment_gate.py \` і `--profile development`
    наступним рядком — аргумент є, регекс його не бачив;
  * ПІДПАРСЕРИ. `release_attestation.py sign --manifest …` не має подавати
    `--attestation`: той обов'язковий лише в підкоманді `verify`.

Тому враховуються лише аргументи ВЕРХНЬОГО парсера — того об'єкта, який повернув
`ArgumentParser(...)`. Аргументи підкоманд поза обсягом: щоб судити їх, треба знати,
яку підкоманду викликано, а це вже розбір командного рядка, не пошук. Перевірка, що
бачить менше, але не бреше, корисніша за ту, чиї знахідки доводиться перебирати.

Звужений сканер знайшов ДРУГУ справжню ваду, якої перший не бачив за шумом:
`Makefile:806 remap-reference-versions` подавала `--database`, якого в парсері немає
ЖОДНОГО, і не подавала жодного з трьох обов'язкових. Коментар над ціллю каже, навіщо
вона є: «скрипт без раннера тест досяжності не вважає частиною системи, і має рацію:
його ніхто не запустить і ніхто не помітить, що він зламався». Зламана була сама ціль.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAKEFILE = ROOT / "Makefile"
CI = ROOT / ".gitlab-ci.yml"

#: `scripts/x.py` і все, що йде за ним до кінця рядка або до `;`/`|`/`&&`.
_INVOCATION = re.compile(r"scripts/([a-z_0-9]+\.py)((?:[^\n;|&]*))")


def _top_level_parsers(tree: ast.Module) -> set[str]:
    """Імена, яким присвоєно `ArgumentParser(...)`. Підпарсери сюди не потрапляють."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        callee = node.value.func
        label = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", "")
        if label != "ArgumentParser":
            continue
        names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _required_flags(script: Path) -> set[str]:
    """Прапорці з `required=True` на ВЕРХНЬОМУ парсері, зняті розбором, а не імпортом."""
    try:
        tree = ast.parse(script.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):  # pragma: no cover - скрипт не парситься
        return set()
    parsers = _top_level_parsers(tree)
    flags: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "add_argument":
            continue
        owner = node.func.value
        if not (isinstance(owner, ast.Name) and owner.id in parsers):
            continue
        required = any(
            kw.arg == "required" and isinstance(kw.value, ast.Constant) and kw.value.value is True
            for kw in node.keywords
        )
        if not required:
            continue
        for argument in node.args:
            if isinstance(argument, ast.Constant) and str(argument.value).startswith("--"):
                flags.add(str(argument.value))
    return flags


def _invocations(text: str) -> list[tuple[str, str]]:
    """Переноси рядків зшиваються: аргумент за `\\` — той самий виклик."""
    joined = re.sub(r"\\\n\s*", " ", text)
    return [(name, tail) for name, tail in _INVOCATION.findall(joined)]


def _missing(text: str, where: str) -> list[str]:
    problems: list[str] = []
    for name, tail in _invocations(text):
        script = ROOT / "scripts" / name
        if not script.is_file():
            continue
        for flag in sorted(_required_flags(script)):
            if flag not in tail:
                problems.append(f"{where}: scripts/{name} викликано без обов'язкового {flag}")
    return problems


def test_the_makefile_supplies_every_required_argument():
    assert _missing(MAKEFILE.read_text(encoding="utf-8"), "Makefile") == []


def test_the_pipeline_supplies_every_required_argument():
    assert _missing(CI.read_text(encoding="utf-8"), ".gitlab-ci.yml") == []


def test_the_scanner_actually_finds_required_flags():
    """Негативний контроль: перевірка, що не бачить жодного обов'язкового прапорця,
    зелена на будь-якому дереві й не означає нічого."""
    gate = ROOT / "scripts/run_exact_environment_gate.py"
    assert gate.is_file()
    assert "--profile" in _required_flags(gate), (
        "розбір не бачить `required=True` навіть там, де він точно є"
    )


def test_the_scanner_notices_a_call_without_the_flag():
    """Другий негативний контроль: сканер мусить ЛОВИТИ порушення, а не лише не падати."""
    poisoned = "\t$(PY) scripts/run_exact_environment_gate.py\n"
    found = _missing(poisoned, "проба")
    assert found and "--profile" in found[0], found
