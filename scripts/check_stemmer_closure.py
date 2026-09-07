#!/usr/bin/env python3
"""Чи зводяться дві форми одного слова до одного терма.

Пошук шукає за основою. Якщо називний і родовий дають РІЗНІ основи, то це два різні
терми, і питання, поставлене живою людиною («обов'язки днювального»), шукає не те, що
заголовок оголосив («Днювальний парку»). Виміряно 01.09.2026 на живому продукті:
називний 14/14, родовий 1/14. Після переходу на збіг за початком слова — 12/14, і два,
що лишились, розходились рівно тут.

Що саме міряється — ВЛАСТИВІСТЬ, не список випадків: для кожної пари форм однієї леми
`_ukrainian_stem(a) == _ukrainian_stem(b)`. Пари беруться із ЗАМОРОЖЕНОГО набору
`evals/datasets/subject_inflection.jsonl`, кожен рядок якого свого часу прогнали на
сервері до внесення. Вигадувати пари тут заборонено: утворений без перевірки родовий
відмінок був би думкою про мову, покладеною в еталон.

Вирівнювання пословне і лише там, де воно справді пословне (однакова кількість слів),
плюс вимога спільного початку в чотири символи. Без другої умови сюди потрапляли б
пари на кшталт «ведення»/«бойових» — різні слова на одній позиції, — і гейт міряв би
не замкненість, а збіг довжин.

    check_stemmer_closure.py            # вимір; спершу САМ прогонить свій контроль
    check_stemmer_closure.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.retrieval_math import _ukrainian_stem, raw_tokens  # noqa: E402

INFLECTION_SET = ROOT / "evals/datasets/subject_inflection.jsonl"

#: Скільки початкових символів мусять збігтися, щоб пара вважалась формами ОДНОГО слова.
#: Чотири — та сама межа, нижче якої стемер не лишає основу.
MIN_SHARED_PREFIX = 4


def _shared_prefix(left: str, right: str) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index


def paradigm_pairs(path: Path) -> list[tuple[str, str, str]]:
    """Пари форм однієї леми із замороженого набору. Порожній набір — це відмова."""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise SystemExit(f"{path} порожній — це відмова, а не результат")
    pairs: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for line in lines:
        row = json.loads(line)
        nominative, genitive = raw_tokens(row["role"]), raw_tokens(row["genitive"])
        if len(nominative) != len(genitive):
            continue
        for left, right in zip(nominative, genitive, strict=True):
            if left == right or _shared_prefix(left, right) < MIN_SHARED_PREFIX:
                continue
            if (left, right) in seen:
                continue
            seen.add((left, right))
            pairs.append((left, right, str(row.get("id"))))
    return pairs


def divergent(
    pairs: list[tuple[str, str, str]], stem: Callable[[str], str]
) -> list[dict[str, str]]:
    return [
        {
            "id": case,
            "nominative": left,
            "genitive": right,
            "left": stem(left),
            "right": stem(right),
        }
        for left, right, case in pairs
        if stem(left) != stem(right)
    ]


def _poisons() -> Iterator[tuple[str, Callable[[str], str]]]:
    """Стемери, які гейт ЗОБОВ'ЯЗАНИЙ відхилити. Без них зелений вирок нічого не важить."""
    yield "тотожність (нічого не знімає)", lambda token: token
    yield (
        "лише словозмінне «ого»",
        lambda token: token[:-3] if token.endswith("ого") and len(token) > 6 else token,
    )
    yield "один список, найдовший збіг (стан до виправлення)", _single_list_stem


def _single_list_stem(token: str) -> str:
    """Стемер до виправлення: словозміна і словотвір в одному списку."""
    if len(token) < 5:
        return token
    for suffix in sorted(
        {"альний", "ого", "ому", "і", "и", "а", "я", "у", "ю"}, key=len, reverse=True
    ):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def selftest(pairs: list[tuple[str, str, str]]) -> list[str]:
    """Негативний контроль, який БІЖИТЬ сам. Перелік, що не бігає, ним не є."""
    survived: list[str] = []
    for name, poison in _poisons():
        if not divergent(pairs, poison):
            survived.append(name)
    return survived


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", type=Path, default=INFLECTION_SET)
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()

    pairs = paradigm_pairs(arguments.set)
    survived = selftest(pairs)
    failures = divergent(pairs, _ukrainian_stem)
    report = {
        "schema": "korpus.stemmer-closure.v1",
        "set": str(arguments.set.relative_to(ROOT)),
        "pairs": len(pairs),
        "converged": len(pairs) - len(failures),
        "divergent": failures,
        "poisons_run": len(list(_poisons())),
        "poisons_survived": survived,
        "status": "PASS" if not failures and not survived and pairs else "FAIL",
    }
    if arguments.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"пар форм однієї леми: {report['pairs']}")
        print(f"зведено до одного терма: {report['converged']}/{report['pairs']}")
        print(f"отрут прогнано: {report['poisons_run']} · вижило: {len(survived)}")
        for item in failures:
            print(
                f"  РОЗБІЖНІСТЬ {item['id']}: {item['nominative']}->{item['left']} "
                f"‖ {item['genitive']}->{item['right']}"
            )
        for name in survived:
            print(f"  ОТРУТА ВИЖИЛА: {name} — гейт не здатен відхилити")
        print(report["status"])
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
