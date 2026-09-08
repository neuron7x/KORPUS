#!/usr/bin/env python3
"""Твердження, які модуль присуду пише ПРО СЕБЕ, перевірені запуском.

Це не другий диференціал. Диференціал ловить розбіжність двох ВИРАЖЕНЬ одного правила;
тут ловиться розбіжність між кодом і прозою, яка про нього написана. Клас відомий цьому
дереву: тест звіряв НАПИСАННЯ (`in source`) і був зелений, поки твердження з його ж
докстрінга було хибне — вада жила під захистом.

Вісім тверджень узято з докстрінгів `answer_adjudication` ДОСЛІВНО і записано в
`config/assurance/adjudication-properties.v1.json` разом із тим, що кожне спростовує.
Протокол прив'язаний хешем ДО прогону: інакше перелік властивостей можна дібрати під те,
що вже проходить.

Домени різні, і це названо. Композиція перевіряється ВИЧЕРПНО — усі 3^4 кортежі вироків
і всі їхні перестановки, тобто повний домен, а не вибірка. Осі перевіряються на
справжніх парах питання-цитата із заморожених `evals/datasets`, тобто на вибірці; там
твердження про ДІАПАЗОН функції (наприклад «ця вісь не вміє відхиляти») лишається
спростовним, але не доведеним.

Негативний контроль обов'язковий: вісім зелених властивостей без насіяних вад доводять
лише, що прогін відбувся. Кожен мутант мусить бути спійманий НАЗВАНОЮ властивістю, і
`status: PASS` вимагає обох умов — нуль контрприкладів І повний recall.

    run_adjudication_properties.py [--out FILE]
    run_adjudication_properties.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from itertools import permutations, product
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT)]

from korpus.application import answer_adjudication as subject  # noqa: E402
from korpus.application.answer_adjudication import AxisVerdict, Verdict  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402

from scripts.release_identity import release_tag  # noqa: E402

PROTOCOL = ROOT / "config/assurance/adjudication-properties.v1.json"
DATASETS = ROOT / "evals/datasets"
VERDICTS: tuple[Verdict, ...] = ("SUPPORTS", "DOES_NOT_SUPPORT", "CANNOT_ADJUDICATE")
#: contested < tangential < supported. Порядок ВПЕВНЕНОСТІ, не алфавіту.
CONFIDENCE = {"contested": 0, "tangential": 1, "supported": 2}
AXES = ("lexical", "structural", "interrogative", "contrast")


@dataclass(frozen=True, slots=True)
class Subject:
    """Функції, які перевіряються. Насіяна вада підмінює одну з них."""

    presentation: Callable[[tuple[AxisVerdict, ...]], str]
    interrogative: Callable[[str, str], AxisVerdict]
    contrast: Callable[[str, str], AxisVerdict]
    lexical: Callable[..., AxisVerdict]


def live() -> Subject:
    return Subject(
        presentation=subject.presentation,
        interrogative=subject._interrogative,
        contrast=subject._contrast,
        lexical=subject._lexical,
    )


def tuples() -> Iterator[tuple[AxisVerdict, ...]]:
    """Повний домен композиції: 3^4 кортежів у сталому порядку осей."""
    for combination in product(VERDICTS, repeat=len(AXES)):
        yield tuple(
            AxisVerdict(axis, verdict, "grid")
            for axis, verdict in zip(AXES, combination, strict=True)
        )


def pairs() -> list[tuple[str, str]]:
    """Справжні пари питання-цитата із заморожених наборів. Не синтетика."""
    quotes: list[str] = []
    questions: list[str] = []
    for line in (DATASETS / "reference.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        # Шістнадцять із дев'яноста п'яти записів цитати не несуть — це випадки, де
        # очікується ВІДМОВА, тож цитувати нема чого. Питання з них беруться однаково.
        if "evidence_sentence" in row:
            quotes.append(str(row["evidence_sentence"]))
        questions.append(str(row["query"]))
    for name, field in (("domain_boundary.jsonl", "query"), ("assurance.jsonl", "query")):
        for line in (DATASETS / name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                questions.append(str(json.loads(line)[field]))
    return [(question, quote) for question in questions for quote in quotes]


#: Свідки класу, якого в замороженому наборі НЕМАЄ. Кожна цитата несе І запитану
#: категорію, І протилежну — саме той випадок, який `_contrast` зобов'язаний ПОЩАДИТИ.
#: Перший узятий дослівно з докстрінга самої осі. Без них твердження про щадіння
#: перевірялося б на порожній множині, а `all([])` істинне: перевірка була б зелена
#: рівно тому, що предмета в домені нема. Виміряно негативним контролем 08.09.2026 —
#: мутант, що знімає перевірку присутності, не був спійманий на самому корпусі.
WITNESSES: tuple[tuple[str, str], ...] = (
    (
        "Коли дозволяється відкривати вогонь по цивільній особі?",
        "Застосування зброї тільки проти воєнних об'єктів, навіть якщо на них перебувають "
        "цивільні особи.",
    ),
    (
        "Які воєнні об'єкти дозволено вражати?",
        "Воєнні об'єкти вражають так, щоб не постраждали цивільні особи.",
    ),
    (
        "Як позначаються свої підрозділи?",
        "Свої підрозділи позначають розпізнавальним знаком, щоб відрізнити від підрозділів "
        "противника.",
    ),
    (
        "Як діяти при виявленні противника?",
        "При виявленні противника командир доповідає і виводить свої сили з-під удару.",
    ),
    (
        "Що робить підрозділ у мирний час?",
        "У мирний час підрозділ несе бойове чергування за графіком.",
    ),
    (
        "Коли відкривати вогонь?",
        "Вогонь відкривають за командою командира і припиняють за його ж командою.",
    ),
)


def _counted(verdicts: tuple[AxisVerdict, ...], value: Verdict) -> int:
    return sum(1 for item in verdicts if item.verdict == value)


def supported_requires_two_and_no_rejection(fns: Subject, _: list[tuple[str, str]]) -> list[Any]:
    bad = []
    for verdicts in tuples():
        earned = _counted(verdicts, "SUPPORTS") >= 2 and _counted(verdicts, "DOES_NOT_SUPPORT") == 0
        if (fns.presentation(verdicts) == "supported") != earned:
            bad.append({"verdicts": [item.verdict for item in verdicts]})
    return bad


def one_rejection_dominates(fns: Subject, _: list[tuple[str, str]]) -> list[Any]:
    return [
        {"verdicts": [item.verdict for item in verdicts]}
        for verdicts in tuples()
        if _counted(verdicts, "DOES_NOT_SUPPORT") and fns.presentation(verdicts) != "contested"
    ]


def abstention_never_raises_confidence(fns: Subject, _: list[tuple[str, str]]) -> list[Any]:
    """Дві умови, і друга з'явилась через негативний контроль.

    Перша редакція перевіряла лише «заміна SUPPORTS на CANNOT_ADJUDICATE не підвищує
    впевненість». Мутант, який РАХУЄ утримання як згоду, її проходив: під ним заміна
    нічого не змінює, бо обидва вироки лічені однаково. Тобто формалізація була слабша
    за прозу, яку цитує. Умова нижче каже те, що сказано словами: утримання не заміщує
    згоди — `supported` вимагає ДВОХ вироків, які буквально є SUPPORTS.
    """
    bad = []
    for verdicts in tuples():
        if fns.presentation(verdicts) == "supported" and _counted(verdicts, "SUPPORTS") < 2:
            bad.append(
                {
                    "verdicts": [item.verdict for item in verdicts],
                    "why": "утримання зарахувалось як згода",
                }
            )
        before = CONFIDENCE[fns.presentation(verdicts)]
        for index, item in enumerate(verdicts):
            if item.verdict != "SUPPORTS":
                continue
            weakened = (
                *verdicts[:index],
                replace(item, verdict="CANNOT_ADJUDICATE"),
                *verdicts[index + 1 :],
            )
            if CONFIDENCE[fns.presentation(weakened)] > before:
                bad.append(
                    {"verdicts": [entry.verdict for entry in verdicts], "weakened_axis": item.axis}
                )
    return bad


def composition_is_order_independent(fns: Subject, _: list[tuple[str, str]]) -> list[Any]:
    bad = []
    for verdicts in tuples():
        outcomes = {fns.presentation(order) for order in permutations(verdicts)}
        if len(outcomes) > 1:
            bad.append(
                {"verdicts": [item.verdict for item in verdicts], "outcomes": sorted(outcomes)}
            )
    return bad


def interrogative_never_rejects(fns: Subject, corpus: list[tuple[str, str]]) -> list[Any]:
    return [
        {"question": question[:80], "quote": quote[:80]}
        for question, quote in corpus
        if fns.interrogative(question, quote).verdict == "DOES_NOT_SUPPORT"
    ]


def contrast_spares_quotes_carrying_both_categories(
    fns: Subject, corpus: list[tuple[str, str]]
) -> list[Any]:
    bad = []
    for question, quote in corpus:
        if fns.contrast(question, quote).verdict != "DOES_NOT_SUPPORT":
            continue
        carries_both = any(
            asked.search(question) and asked.search(quote) and opposite.search(quote)
            for asked, opposite in subject._CONTRASTS
        )
        if carries_both:
            bad.append({"question": question[:80], "quote": quote[:80]})
    return bad


def unrecognised_kind_abstains(fns: Subject, corpus: list[tuple[str, str]]) -> list[Any]:
    return [
        {"question": question[:80]}
        for question, quote in corpus
        if subject.question_kind(question) is None
        and fns.interrogative(question, quote).verdict != "CANNOT_ADJUDICATE"
    ]


def lexical_abstains_only_for_declared_subject(fns: Subject, _: list[tuple[str, str]]) -> list[Any]:
    bad = []
    grid = product([0.0, 0.25, 0.5, 0.75, 1.0], [0.0, 0.25, 0.5, 0.75, 1.0], [False, True])
    for coverage, threshold, declared in grid:
        got = fns.lexical(coverage, threshold, subject_declared=declared).verdict
        expected = (
            "SUPPORTS"
            if coverage >= threshold
            else ("CANNOT_ADJUDICATE" if declared else "DOES_NOT_SUPPORT")
        )
        if got != expected:
            bad.append(
                {
                    "coverage": coverage,
                    "threshold": threshold,
                    "subject_declared": declared,
                    "verdict": got,
                    "expected": expected,
                }
            )
    return bad


CLAIMS: dict[str, Callable[[Subject, list[tuple[str, str]]], list[Any]]] = {
    "supported_requires_two_and_no_rejection": supported_requires_two_and_no_rejection,
    "one_rejection_dominates": one_rejection_dominates,
    "abstention_never_raises_confidence": abstention_never_raises_confidence,
    "composition_is_order_independent": composition_is_order_independent,
    "interrogative_never_rejects": interrogative_never_rejects,
    "contrast_spares_quotes_carrying_both_categories": contrast_spares_quotes_carrying_both_categories,
    "unrecognised_kind_abstains": unrecognised_kind_abstains,
    "lexical_abstains_only_for_declared_subject": lexical_abstains_only_for_declared_subject,
}


def _rejecting_interrogative(question: str, quote: str) -> AxisVerdict:
    verdict = subject._interrogative(question, quote)
    if verdict.verdict == "CANNOT_ADJUDICATE" and subject.question_kind(question) is not None:
        return replace(verdict, verdict="DOES_NOT_SUPPORT")
    return verdict


def _supporting_unknown_kind(question: str, quote: str) -> AxisVerdict:
    if subject.question_kind(question) is None:
        return AxisVerdict("interrogative", "SUPPORTS", "мутант: невпізнаний тип схвалює")
    return subject._interrogative(question, quote)


def _contrast_ignoring_presence(question: str, quote: str) -> AxisVerdict:
    if not subject.is_question(question):
        return subject._contrast(question, quote)
    for asked, opposite in subject._CONTRASTS:
        if asked.search(question) and opposite.search(quote):
            return AxisVerdict(
                "contrast", "DOES_NOT_SUPPORT", "мутант: присутність не перевіряється"
            )
    return subject._contrast(question, quote)


def _composer(
    *,
    one_axis: bool = False,
    ignore_rejection: bool = False,
    count_abstention: bool = False,
    first_decides: bool = False,
) -> Callable[[tuple[AxisVerdict, ...]], str]:
    """ОДИН параметризований композитор замість чотирьох копій.

    Кожен прапорець називає рівно одну правдоподібну ваду злиття. Чотири копії дали б
    менше аргументів і більше місць розійтися з тим, що вони мали б відтворювати.
    """

    def compose(verdicts: tuple[AxisVerdict, ...]) -> str:
        if first_decides:
            return {
                "SUPPORTS": "supported",
                "DOES_NOT_SUPPORT": "contested",
                "CANNOT_ADJUDICATE": "tangential",
            }[verdicts[0].verdict]
        if not ignore_rejection and _counted(verdicts, "DOES_NOT_SUPPORT"):
            return "contested"
        agreeing = _counted(verdicts, "SUPPORTS")
        if count_abstention:
            agreeing += _counted(verdicts, "CANNOT_ADJUDICATE")
        return "supported" if agreeing >= (1 if one_axis else 2) else "tangential"

    return compose


MUTANTS: dict[str, Subject] = {
    "one_axis_is_enough": replace(live(), presentation=_composer(one_axis=True)),
    "rejection_ignored": replace(live(), presentation=_composer(ignore_rejection=True)),
    "abstention_counts_as_support": replace(live(), presentation=_composer(count_abstention=True)),
    "first_axis_decides": replace(live(), presentation=_composer(first_decides=True)),
    "interrogative_rejects_on_absence": replace(live(), interrogative=_rejecting_interrogative),
    "contrast_ignores_presence": replace(live(), contrast=_contrast_ignoring_presence),
    "interrogative_supports_unknown_kind": replace(live(), interrogative=_supporting_unknown_kind),
    "lexical_abstains_always": replace(
        live(),
        lexical=lambda coverage, threshold, *, subject_declared=False: AxisVerdict(
            "lexical", "CANNOT_ADJUDICATE", "мутант: завжди утримується"
        ),
    ),
}


def evaluate(fns: Subject, corpus: list[tuple[str, str]]) -> dict[str, list[Any]]:
    return {name: claim(fns, corpus) for name, claim in CLAIMS.items()}


def contrast_population(corpus: list[tuple[str, str]]) -> int:
    """Скільки пар узагалі належать класу, про який твердження щадіння.

    Порожня популяція означала б, що перевірка зелена через ВІДСУТНІСТЬ предмета —
    той самий `all([])`, який це дерево вже називало вадою.
    """
    return sum(
        1
        for question, quote in corpus
        for asked, opposite in subject._CONTRASTS
        if asked.search(question) and asked.search(quote) and opposite.search(quote)
    )


def recall(protocol: dict[str, Any], corpus: list[tuple[str, str]]) -> tuple[float, list[str]]:
    """Кожен мутант мусить бути спійманий саме НАЗВАНОЮ властивістю, не будь-якою."""
    missed: list[str] = []
    for entry in protocol["negative_control"]["mutants"]:
        claim = CLAIMS[entry["breaks"]]
        if not claim(MUTANTS[entry["id"]], corpus):
            missed.append(f"{entry['id']} -> {entry['breaks']}")
    total = len(protocol["negative_control"]["mutants"])
    return (total - len(missed)) / total, missed


def selftest() -> int:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    corpus = [*pairs(), *WITNESSES]
    score, missed = recall(protocol, corpus)
    declared = {entry["id"] for entry in protocol["claims"]}
    problems = list(missed)
    if declared != set(CLAIMS):
        problems.append(f"протокол і код називають різні твердження: {declared ^ set(CLAIMS)}")
    print(
        json.dumps(
            {
                "selftest": "korpus.adjudication-properties",
                "claims": len(CLAIMS),
                "mutants": len(MUTANTS),
                "recall": score,
                "missed": missed,
                "failures": problems,
            },
            ensure_ascii=False,
        )
    )
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=ROOT / "var/production/adjudication-properties.json"
    )
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()

    protocol_bytes = PROTOCOL.read_bytes()
    protocol = json.loads(protocol_bytes.decode("utf-8"))
    corpus = [*pairs(), *WITNESSES]
    results = evaluate(live(), corpus)
    score, missed = recall(protocol, corpus)
    counterexamples = {name: found for name, found in results.items() if found}
    report = {
        "schema": "korpus.adjudication-properties.v1",
        # Нуль контрприкладів при recall < 1 — НЕ PASS: це твердження про перевірку.
        "status": "PASS" if not counterexamples and score == 1.0 else "FAIL",
        "subject": protocol["subject"],
        "preregistration_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
        "claims_checked": len(CLAIMS),
        "composition_domain": {"verdict_tuples": len(VERDICTS) ** len(AXES), "exhaustive": True},
        "axis_domain": {
            "question_quote_pairs": len(corpus),
            "witnesses": len(WITNESSES),
            "contrast_population": contrast_population(corpus),
            "exhaustive": False,
        },
        "counterexamples": counterexamples,
        "seeded_defects": len(MUTANTS),
        "recall": score,
        "missed_seeds": missed,
        "evidence_class": protocol["evidence_class"],
        "ceiling": protocol["ceiling"],
        "source_tree_sha256": compute_source_digest(ROOT),
        "release": release_tag(),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
