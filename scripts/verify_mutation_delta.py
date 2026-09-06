#!/usr/bin/env python3
"""Контур, що застосовується сам: НОВИЙ код мусить прийти зі своїм спростуванням.

Дві наявні лінії захисту тримають дерево, і жодна не тримає цього:

* ратчет покриття (`maximum_missing_branch_regression: 0`) не дає новому коду
  лишитись невиконаним — але виконана гілка ще не є перевіреною;
* курована мутація вбиває 624 мутанти з 624 — і це число ПРО КАТАЛОГ. Сам
  `probe_uncatalogued_mutation.py` виміряв 2026-08-29, що 162 модулі й 15 853
  рядки — 42% джерела — не мають жодного мутанта.

Отже новий модуль зі стовідсотковим покриттям тестами, які нічого не стверджують,
проходить обидві: гілки взято, у каталозі його немає. Проба це бачить, але
навмисно не є гейтом.

Тут вона стає гейтом РІВНО НА ДЕЛЬТІ. Не на дереві: 162 модулі — це міграція на
тижні, а правило, що вимагає міграції, є вартістю, перевдягненою в інваріант
(§20 «виміряй популяцію перед правилом»). Дельта одного злиття — одиниці модулів.

Для кожного .py під `apps/api/src`, доданого або зміненого між merge-base і HEAD,
істинним має бути ОДНЕ з трьох:

    1. модуль присутній у курованому каталозі `run_mutation_tests.py`;
    2. проба вбиває всіх засіяних у ньому мутантів;
    3. є запис у `config/operations/mutation-delta-exceptions.json` із полями
       {module, class, on, reason, closes_when} — той самий патерн, що
       `gate-closure.json`, бо виняток без умови свого закриття є вічним.

    verify_mutation_delta.py [--base origin/main] [--sample N] [--selftest]
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "apps/api/src"))

CATALOGUE = ROOT / "scripts/run_mutation_tests.py"
EXCEPTIONS = ROOT / "config/operations/mutation-delta-exceptions.json"
#: Предмет гейта — не «код застосунку», а те, що курований каталог УЖЕ мутує.
#: Виміряно 2026-09-06: у каталозі 214 записів — apps 143, scripts 68, deploy 2,
#: Makefile 1. Фільтр `apps/api/src/` звужував предмет до двох третин і мовчав про
#: `scripts/`, де живуть самі гейти. Гейт, сліпий до половини джерела, гірший за
#: відсутній: він створює враження покриття там, де його немає.
SOURCE_PREFIXES = ("apps/api/src/", "scripts/")
REQUIRED_EXCEPTION_FIELDS = ("module", "class", "on", "reason", "closes_when")


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return done.stdout.strip()


def catalogued_modules() -> set[str]:
    """Шляхи, які курований каталог справді мутує — з AST, не з тексту.

    Пошук підрядком порахував би згадку в коментарі за покриття: та сама вада,
    через яку `gate_source_bound` колись читав не той файл.
    """
    tree = ast.parse(CATALOGUE.read_text(encoding="utf-8"))
    files: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and getattr(node.func, "id", "") == "Mutant"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            files.add(node.args[1].value)
    return files


def changed_modules(base: str) -> list[str]:
    merge_base = _git("merge-base", base, "HEAD")
    if not merge_base:
        raise SystemExit(f"немає merge-base з {base}: предмет виміру не визначений")
    names = _git("diff", "--name-only", "--diff-filter=AM", merge_base, "HEAD").splitlines()
    return sorted(
        name
        for name in names
        if name.startswith(SOURCE_PREFIXES)
        and name.endswith(".py")
        and not name.endswith("__init__.py")
        and (ROOT / name).is_file()
    )


def load_exceptions() -> dict[str, dict[str, Any]]:
    if not EXCEPTIONS.is_file():
        return {}
    payload = json.loads(EXCEPTIONS.read_text(encoding="utf-8"))
    accepted = payload.get("accepted", [])
    out: dict[str, dict[str, Any]] = {}
    for item in accepted:
        missing = [field for field in REQUIRED_EXCEPTION_FIELDS if not item.get(field)]
        if missing:
            # Виняток без умови закриття — вічний. Реєстр, який його приймає,
            # перестає бути реєстром боргу й стає списком дозволів.
            raise SystemExit(f"виняток без обов'язкових полів {missing}: {item.get('module')}")
        out[str(item["module"])] = item
    return out


def classify(base: str) -> dict[str, Any]:
    catalogued = catalogued_modules()
    exceptions = load_exceptions()
    verdicts = []
    for module in changed_modules(base):
        if module in catalogued:
            state = "CATALOGUED"
        elif module in exceptions:
            state = "EXCEPTED"
        else:
            state = "NEEDS_PROBE"
        verdicts.append({"module": module, "state": state})
    return {
        "schema": "korpus.mutation-delta-gate.v1",
        "base": base,
        "merge_base": _git("merge-base", base, "HEAD"),
        "head": _git("rev-parse", "HEAD"),
        "modules": verdicts,
        "needs_probe": [item["module"] for item in verdicts if item["state"] == "NEEDS_PROBE"],
    }


def selftest() -> int:
    """Негативні контролі. Гейт без них — оголошення, а не гейт."""
    failures = []
    catalogued = catalogued_modules()
    if len(catalogued) < 50:
        failures.append(f"каталог розпізнано лише на {len(catalogued)} модулів — розбір зламався")
    fake = "apps/api/src/korpus/application/__does_not_exist__.py"
    if fake in catalogued:
        failures.append("неіснуючий модуль визнано каталогізованим")
    try:
        load_exceptions()
    except SystemExit as error:
        failures.append(f"реєстр винятків не читається: {error}")
    print(
        json.dumps(
            {"selftest": "PASS" if not failures else "FAIL", "failures": failures},
            ensure_ascii=False,
        )
    )
    return 0 if not failures else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # БЕЗ дефолту. Я прибрав `origin/main` лише з рецепта make і оголосив ваду
    # закритою — а CI кличе скрипт НАПРЯМУ, тож дефолт лишався живий і давав
    # порожню дельту з rc=0. Прибрано було не значення, а потребу його надрукувати.
    # Виміряно незалежним аудитом 06.09.2026.
    # Обовʼязковий для КЛАСИФІКАЦІЇ, не для самоперевірки: `--selftest` не має
    # предмета порівняння і бази не потребує. `required=True` глобально зламав його
    # у лані — я прибрав дефолт і не прогнав другий режим. Перевірка нижче тримає
    # обидві властивості: дефолту немає, і селфтест лишається досяжним.
    parser.add_argument("--base")
    parser.add_argument("--out", type=Path, default=ROOT / "var/mutation-delta-gate.json")
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    if not arguments.base:
        parser.error("--base обовʼязковий: без бази порівняння предмет дельти не визначений")
    report = classify(arguments.base)
    report["status"] = "PASS" if not report["needs_probe"] else "NEEDS_PROBE"
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
