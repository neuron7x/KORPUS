"""Оголошений порядок класів доказу не має спостережуваного наслідку в нижніх трьох.

ВИМІРЯНО 02.09.2026 зовнішнім рецензентом і перевірено тут запуском.

`docs/formal/ASSURANCE_ALGEBRA.md:15` оголошує СТРОГИЙ ланцюг:

    NONE < DECLARATIVE < STATIC < EXECUTED < EXECUTED_WITH_NEGATIVE_CONTROL
        < INDEPENDENT_ATTESTED

Але `assurance_calculus.evidence_ceiling` галузиться не на класі, а на ПРАПОРЦЯХ:

    if not evidence.executed:            return ceiling_without_execution              # 70.0
    if not evidence.negative_control:    return ceiling_without_negative_control       # 90.0
    if not (independent and attested):   return ceiling_without_independent_attestation # 97.0
    return 100.0

Отже `NONE`, `DECLARATIVE` і `STATIC` дають ОДНАКОВУ стелю 70.0: три елементи строгого
порядку злиті в один спостережуваний стан. Строга нерівність без різниці у вироці — не
вимір, а нотація.

ЩО САМЕ ЦЕЙ ТЕСТ ТРИМАЄ. Він не вимагає, щоб стелі розрізнялися: скільки рівнів мати —
рішення того, хто приймає систему. Він вимагає, щоб РОЗБІЖНІСТЬ між оголошеним порядком і
спостережуваним наслідком була НАЗВАНОЮ. Якщо стелі почнуть розрізняти нижні три класи,
тест почервоніє й змусить оновити цей опис; якщо оголошений порядок скоротять до
спостережуваного — теж.

Спорідненість із рештою дерева: це той самий клас, що «сигнал із нульовою ентропією не є
виміром». Три різні входи, один вихід — розрізнення оголошене й не існує.
"""

from __future__ import annotations

import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
calculus = importlib.import_module("korpus.application.assurance_calculus")


def _point(**flags):
    """Точка доказу з явно названими прапорцями; клас — лише мітка."""
    label = flags.pop("evidence_class", "NONE")
    return calculus.EvidencePoint(
        evidence_class=calculus.EvidenceClass[label],
        source_digest="0" * 64,
        release="v0.0.0",
        status="PASS",
        executed=bool(flags.get("executed", False)),
        negative_control=bool(flags.get("negative_control", False)),
        independent=bool(flags.get("independent", False)),
        attested=bool(flags.get("attested", False)),
    )


def _ceiling(policy, point) -> float:
    return calculus.evidence_ceiling(policy, point)


def test_the_lowest_three_classes_share_one_ceiling():
    policy = calculus.DimensionPolicy("проба", 1.0)
    ceilings = {
        name: _ceiling(policy, _point(evidence_class=name))
        for name in ("NONE", "DECLARATIVE", "STATIC")
    }
    assert len(set(ceilings.values())) == 1, (
        "нижні три класи почали розрізнятися стелею — оголошений порядок нарешті має "
        f"наслідок, і опис у docs/formal/ASSURANCE_ALGEBRA.md треба оновити: {ceilings}"
    )


def test_the_class_does_constrain_which_points_are_constructible():
    """Уточнення до знахідки рецензента, здобуте ЗАПУСКОМ.

    Теза «мітка класу не впливає ні на що» завелика: `EvidencePoint.__post_init__`
    заборонає незлагоджені пари — клас ≥ EXECUTED вимагає `executed=True`, а
    `independent`/`attested` звіряються в обидва боки. Тобто клас обмежує МНОЖИНУ
    конструйовних точок.

    Чинним лишається вужче й точніше твердження: у межах конструйовної множини стелю
    визначають ПРАПОРЦІ, і нижні три класи від того нерозрізненні (тест вище).
    """
    import pytest

    with pytest.raises(ValueError):
        _point(evidence_class="EXECUTED")  # клас вимагає виконання, прапорця немає

    with pytest.raises(ValueError):
        _point(evidence_class="NONE", independent=True, attested=True)


def test_the_flags_do_change_the_ceiling():
    """Позитивний контроль: без нього тест про однакову стелю був би зелений і на мертвій функції."""
    policy = calculus.DimensionPolicy("проба", 1.0)
    steps = [
        _ceiling(policy, _point(evidence_class="NONE")),
        _ceiling(policy, _point(evidence_class="EXECUTED", executed=True)),
        _ceiling(
            policy,
            _point(
                evidence_class="EXECUTED_WITH_NEGATIVE_CONTROL",
                executed=True,
                negative_control=True,
            ),
        ),
        _ceiling(
            policy,
            _point(
                evidence_class="INDEPENDENT_ATTESTED",
                executed=True,
                negative_control=True,
                independent=True,
                attested=True,
            ),
        ),
    ]
    assert steps == sorted(steps) and len(set(steps)) == 4, (
        f"прапорці перестали розрізняти стелю — функція мертва: {steps}"
    )
