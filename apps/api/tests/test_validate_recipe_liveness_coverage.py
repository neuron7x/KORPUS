"""Валідатори, які `make validate` запускає ВЛАСНИМ рецептом, мусять мати отруту.

`validate` складається з двох різних речей: тридцяти з чимось цілей-передумов і трьох
викликів python просто в рецепті — `validate_repository`, `validate_infrastructure`,
`validate_kubernetes`. Перші видно кожному переліку цілей; другі видно лише тому, хто
читає сам рецепт, і саме тому вони прожили до 02.09.2026 БЕЗ ЖОДНОЇ оголошеної отрути:
десять гейтів у `gate-liveness.yaml` не покривали жодного з трьох.

Три з них охороняють найдорожче: обов'язкові файли реєстру й відстежувані секрети
(repository), загартування контейнерів compose (infrastructure), незапінований образ і
записувана коренева ФС у ПРОДАКШЕННОМУ оверлеї (kubernetes). Гейт без отрути — це
твердження про властивість, якого ніхто не переміряв.

Тест читає РЕЦЕПТ, а не копію переліку: копія розійшлася б мовчки, і саме мовчазне
розходження і є тим, від чого цей тест існує.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
MAKEFILE = ROOT / "Makefile"
LIVENESS = ROOT / "config/operations/gate-liveness.yaml"

#: `scripts/validate_repository.py` -> ім'я гейта, під яким він оголошений.
_SCRIPT = re.compile(r"scripts/(validate_[a-z_]+)\.py")


def _validate_recipe() -> str:
    text = MAKEFILE.read_text(encoding="utf-8")
    found = re.search(r"^validate:[^\n]*\n((?:\t[^\n]*\n)*)", text, re.M)
    assert found is not None, "у Makefile немає правила validate:"
    return found.group(1)


def _declared_gates() -> dict[str, dict]:
    document = yaml.safe_load(LIVENESS.read_text(encoding="utf-8"))
    return {gate["name"]: gate for gate in document["gates"]}


def test_every_validator_in_the_validate_recipe_declares_a_poison() -> None:
    scripts = sorted(set(_SCRIPT.findall(_validate_recipe())))
    assert scripts, "рецепт validate не викликає жодного validate_*.py — якір зник"
    gates = _declared_gates()
    undeclared: list[str] = []
    unarmed: list[str] = []
    for script in scripts:
        name = script.replace("_", "-")
        gate = gates.get(name)
        if gate is None:
            undeclared.append(f"{script} -> немає гейта {name!r}")
        elif not gate.get("poisons"):
            unarmed.append(f"{name} оголошено без жодної отрути")
    assert not undeclared, undeclared
    assert not unarmed, unarmed


def test_the_gate_that_measures_git_state_keeps_git_in_its_probe_copy() -> None:
    """Без `.git` копія не має відстежуваних шляхів, і гейт падає на ЧИСТОМУ стані.

    Це читалось би як «гейт зламаний», хоча він працює правильно на іншому предметі.
    Виміряно 02.09.2026: `validate-repository` дав ONE_WAY_FAIL саме через це.
    """
    gate = _declared_gates()["validate-repository"]
    assert ".git" in (gate.get("keep") or []), (
        "validate_repository міряє git-стан; без keep=[.git] проба відхиляє чистий стан"
    )


def test_an_ambiguous_poison_anchor_names_which_occurrence_it_means() -> None:
    """Отрута, чий якір збігається двічі, псує ПЕРШИЙ збіг, а не названий предмет."""
    for gate in _declared_gates().values():
        for poison in gate.get("poisons") or []:
            if poison.get("kind") != "replace":
                continue
            target = ROOT / poison["target"]
            if not target.is_file():
                continue
            hits = target.read_text(encoding="utf-8", errors="ignore").count(poison["find"])
            if hits > 1:
                assert poison.get("occurrence"), (
                    f"{gate['name']}/{poison['name']}: якір збігається {hits} разів "
                    "без `occurrence` — отрута зіпсує не той предмет, який називає"
                )
