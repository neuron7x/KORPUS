#!/usr/bin/env python3
"""Друга реалізація присуду допуску, і вимір РОЗБІЖНОСТЕЙ із виробничою.

Навіщо це існує. Соло-власник не може купити незалежність ІНТЕРЕСУ: скільки агентів не
запусти, усі несуть інтерес того, хто їх запустив, і `evidence-classes.v1.json` це вже
знає — `aggregation.cross_source_join: forbidden` забороняє склеювати згоду джерел у
доказ. Незалежність СЕРЕДОВИЩА виміряна 08.09.2026 і закрита на обох дзеркалах
(`reports/closure/HOSTED_BUILDER_ROAD_2026-09-08.json`). Лишаються дві осі, які
обчислення дати може: МЕТОД і ЧАС. Цей скрипт — обидві.

МЕТОД: правило допуску виражене вдруге, іншими засобами. Виробнича реалізація рахує
маржі відніманням і порівнює з нулем; довідкова порівнює величини напряму, а
структурну умову бере ТОТОЖНІСТЮ enum, а не рядком `.value`. Дві реалізації, що
збігаються текстуально, розбіжності не дають за побудовою — тому різниця у ВИРАЖЕННІ
записана в протоколі як вимога.

ЧАС: сітка входів і означення розбіжності зафіксовані в
`config/assurance/admission-differential-protocol.v1.json` і прив'язані хешем. Без цього
нуль розбіжностей означав би вибір сітки після того, як стало видно результат.

СТЕЛЯ, названа явно: rank 4. Це НЕ незалежна оцінка. Диференціал може лише ЗНИЖУВАТИ
впевненість — знаходити розбіжності — і ніколи не засвідчує їх відсутності. Нуль
розбіжностей є твердженням про предмет ЛИШЕ тоді, коли recall негативного контролю
дорівнює одиниці; інакше це твердження про сам диференціал.

    run_admission_differential.py [--out FILE]
    run_admission_differential.py --selftest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT)]

from korpus.application.evidence_admission import evidence_is_eligible  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from korpus.application.retrieval import AUTHORITY_PRIOR  # noqa: E402
from korpus.application.risk import RiskThresholds  # noqa: E402
from korpus.domain.models import AuthorityClass, RetrievedEvidence, ReviewState  # noqa: E402

from scripts.release_identity import release_tag  # noqa: E402

PROTOCOL = ROOT / "config/assurance/admission-differential-protocol.v1.json"
#: Крок обабіч порога. Клас нічиєї тут щільний, і саме на ньому вже помилялись.
EPSILON = 1e-9
NON_NORMATIVE = frozenset({AuthorityClass.ADVERSARY, AuthorityClass.UNKNOWN})


@dataclass(frozen=True, slots=True)
class Case:
    profile: str
    review_state: ReviewState
    authority: AuthorityClass
    score: float
    coverage: float
    declares_the_subject: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "review_state": self.review_state.value,
            "authority": self.authority.value,
            "score": self.score,
            "query_coverage": self.coverage,
            "declares_the_subject": self.declares_the_subject,
        }


def reference_eligible(case: Case, thresholds: RiskThresholds) -> bool:
    """Правило допуску, записане з ДОКСТРІНГІВ, а не з коду.

    Три навмисні відмінності у вираженні: тотожність enum замість рядка `.value`,
    членство в множині ненормативних замість властивості `is_normative`, і пряме
    порівняння величин замість маржі з нулем.
    """
    if case.review_state is not ReviewState.APPROVED:
        return False
    if case.authority in NON_NORMATIVE:
        return False
    if case.declares_the_subject:
        return True
    return (
        case.score >= thresholds.minimum_score
        and case.coverage >= thresholds.minimum_query_coverage
        and AUTHORITY_PRIOR[case.authority] >= thresholds.minimum_authority
    )


def item_of(case: Case) -> RetrievedEvidence:
    """Структурна заглушка тієї самої форми, яку читають виробничі функції.

    `SimpleNamespace` тут не спрощення: рівно так будує вхід власний
    `apps/api/tests/test_admission_tie.py`, і виробничі функції качино типізовані по цих
    полях. Стани, яких pydantic не пропустив би, у сітці НЕ породжуються: `review_state`
    завжди справжній член enum, тож `.value` і тотожність описують один предмет.
    """
    stand_in = SimpleNamespace(
        score=case.score,
        query_coverage=case.coverage,
        span=SimpleNamespace(id="span-differential"),
        version=SimpleNamespace(review_state=case.review_state, authority=case.authority),
    )
    # `cast`, не побудова моделі: виробничі функції читають РІВНО чотири поля, а повний
    # `RetrievedEvidence` додав би десяток, яких правило не торкається, і сітка стала б
    # твердженням про конструктор моделі замість твердження про правило.
    return cast(RetrievedEvidence, stand_in)


def cases(protocol: dict[str, Any]) -> Iterator[tuple[Case, RiskThresholds]]:
    """Сітка входів як ДОБУТОК осей, а не як п'ять вкладених циклів.

    `itertools.product` тут не смак: вкладеність шість рівнів робила саму сітку
    найскладнішим місцем файла, тобто вимірювач був би заплутаніший за предмет.
    """
    coverages = [0.0, 0.25, 1 / 3, 0.5, 2 / 3, 0.75, 1.0]
    for profile in protocol["grid"]["threshold_profiles"]:
        thresholds = RiskThresholds(
            minimum_score=profile["minimum_score"],
            minimum_query_coverage=profile["minimum_query_coverage"],
            minimum_support_score=profile["minimum_support_score"],
            minimum_authority=profile["minimum_authority"],
        )
        floor = thresholds.minimum_score
        scores = [0.0, max(0.0, floor - EPSILON), floor, min(1.0, floor + EPSILON), 1.0]
        axes = product(ReviewState, AuthorityClass, scores, coverages, (False, True))
        for state, authority, score, coverage, declares in axes:
            yield (
                Case(
                    profile=profile["name"],
                    review_state=state,
                    authority=authority,
                    score=score,
                    coverage=coverage,
                    declares_the_subject=declares,
                ),
                thresholds,
            )


Rule = Callable[[Case, RiskThresholds], bool]


def divergences(
    protocol: dict[str, Any],
    subject: Rule,
) -> tuple[int, list[dict[str, Any]]]:
    """Входи, на яких предмет і довідкова реалізація дають різний присуд."""
    found: list[dict[str, Any]] = []
    total = 0
    for case, thresholds in cases(protocol):
        total += 1
        produced = subject(case, thresholds)
        expected = reference_eligible(case, thresholds)
        if produced != expected:
            found.append({**case.as_dict(), "production": produced, "reference": expected})
    return total, found


def production(case: Case, thresholds: RiskThresholds) -> bool:
    return evidence_is_eligible(
        item_of(case), thresholds, declares_the_subject=case.declares_the_subject
    )


#: Насіння відомих вад. Кожне — правдоподібна правка ПРАВИЛА, і кожне мусить дати
#: розбіжність. Recall нижче одиниці означає, що чистий нуль нічого не стверджує.
def _seed(
    *,
    score_strict: bool = False,
    coverage_strict: bool = False,
    authority_strict: bool = False,
    check_review_state: bool = True,
    check_normative: bool = True,
    subject_first: bool = False,
    honour_subject: bool = True,
) -> Rule:
    def rule(case: Case, thresholds: RiskThresholds) -> bool:
        lexical = (
            (
                case.score > thresholds.minimum_score
                if score_strict
                else case.score >= thresholds.minimum_score
            )
            and (
                case.coverage > thresholds.minimum_query_coverage
                if coverage_strict
                else case.coverage >= thresholds.minimum_query_coverage
            )
            and (
                AUTHORITY_PRIOR[case.authority] > thresholds.minimum_authority
                if authority_strict
                else AUTHORITY_PRIOR[case.authority] >= thresholds.minimum_authority
            )
        )
        if subject_first and case.declares_the_subject:
            return True
        if check_review_state and case.review_state is not ReviewState.APPROVED:
            return False
        if check_normative and case.authority in NON_NORMATIVE:
            return False
        if honour_subject and case.declares_the_subject:
            return True
        return lexical

    return rule


SEEDS: dict[str, Rule] = {
    "strict_score": _seed(score_strict=True),
    "strict_coverage": _seed(coverage_strict=True),
    "strict_authority": _seed(authority_strict=True),
    "dropped_review_state": _seed(check_review_state=False),
    "dropped_normative": _seed(check_normative=False),
    "subject_bypasses_structure": _seed(subject_first=True),
    "subject_ignored": _seed(honour_subject=False),
}


def selftest() -> int:
    """Negative control. Кожна насіяна вада мусить бути ЗНАЙДЕНА; чисте правило — ні."""
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    missed = [name for name, seeded in SEEDS.items() if not divergences(protocol, seeded)[1]]
    _, clean = divergences(protocol, production)
    problems = list(missed)
    if clean:
        problems.append(
            f"довідкова реалізація розходиться з виробничою на {len(clean)} входах ЧИСТОГО "
            "прогону: доти кожна «розбіжність» описує диференціал, а не предмет"
        )
    print(
        json.dumps(
            {
                "selftest": "korpus.admission-differential",
                "seeded_defects": len(SEEDS),
                "recall": (len(SEEDS) - len(missed)) / len(SEEDS),
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
        "--out", type=Path, default=ROOT / "var/production/admission-differential.json"
    )
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()

    protocol_bytes = PROTOCOL.read_bytes()
    protocol = json.loads(protocol_bytes.decode("utf-8"))
    total, found = divergences(protocol, production)
    missed = [name for name, seeded in SEEDS.items() if not divergences(protocol, seeded)[1]]
    recall = (len(SEEDS) - len(missed)) / len(SEEDS)
    report = {
        "schema": "korpus.admission-differential.v1",
        # Нуль розбіжностей при recall < 1 — НЕ PASS: це твердження про диференціал.
        "status": "PASS" if not found and recall == 1.0 else "FAIL",
        "subject": protocol["subject"],
        "preregistration_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
        "cases": total,
        "divergences": found,
        "seeded_defects": len(SEEDS),
        "seeded_defects_detected": len(SEEDS) - len(missed),
        "recall": recall,
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
