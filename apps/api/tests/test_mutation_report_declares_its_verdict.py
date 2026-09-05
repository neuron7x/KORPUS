"""Артефакт, який цитують як доказ, мусить ОГОЛОШУВАТИ свій вирок.

ВИМІРЯНО 02.09.2026. `reports/MUTATION_FULL_CATALOGUE_CURRENT.json` — доказ під
претензією CLM-MUTATION у журналі релізу. Після того, як читач прив'язки навчився
бачити конверт `provenance`, каталог прив'язався ПРАВИЛЬНО і все одно дістав
`UNDECLARED_EVIDENCE`: поля вироку в ньому не було взагалі. Вирок доводилось виводити
з `mutation_score`, тобто тримати знання про предмет у читачі.

Читач, що виводить вирок сам, розходиться з предметом МОВЧКИ, щойно предмет зміниться:
`mutation_score` ділить на мутантів, які ще ЗАСТОСОВУЮТЬСЯ, тож мутант, чий рядок
переформатували, тихо залишає знаменник, і 1.0 лишається на місці при каталозі, що
всихає. Саме тому вирок рахується з `mutation_score_over_catalogue` і з переліків
survived/invalid/errors, а не з одного числа.

Порожній перелік результатів — окремий випадок і НЕ успіх: `all([])` істинне, а нуль
мутантів означає, що каталог не бігав.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "apps/api/src"))

from run_mutation_tests import summarize  # noqa: E402


def _result(identifier: str, status: str) -> dict[str, object]:
    return {"id": identifier, "status": status}


def _verdict(results: list[dict[str, object]]) -> str:
    return str(summarize(results, shard_index=None, shard_count=1)["status"])


def test_a_clean_catalogue_declares_pass() -> None:
    assert _verdict([_result("M01", "KILLED"), _result("M02", "KILLED")]) == "PASS"


def test_a_survivor_declares_fail() -> None:
    assert _verdict([_result("M01", "KILLED"), _result("M02", "SURVIVED")]) == "FAIL"


def test_an_invalid_mutant_declares_fail() -> None:
    """Мутант, що перестав застосовуватись, залишає знаменник `mutation_score`.

    Без цього рядка `mutation_score` лишився б 1.0 при каталозі, що всихає — рівно те,
    що сталося 03.08.2026 з M04, M17, M19 і M25 після переносу рядків лінтером.
    """
    assert _verdict([_result("M01", "KILLED"), _result("M02", "INVALID")]) == "FAIL"


def test_an_errored_mutant_declares_fail() -> None:
    assert _verdict([_result("M01", "KILLED"), _result("M02", "ERROR")]) == "FAIL"


def test_an_empty_catalogue_is_not_success() -> None:
    """`all([])` істинне. Нуль мутантів означає, що каталог не бігав, а не що він чистий."""
    assert _verdict([]) == "FAIL"


def test_the_shipped_catalogue_declares_a_verdict() -> None:
    """Негативний контроль до всього файла: поле мусить бути В АРТЕФАКТІ, не лише у функції.

    Перевірки вище звіряють `summarize`. Але претензію CLM-MUTATION підпирає ФАЙЛ, і якщо
    запис на диск колись перестане нести це поле, кожне твердження вище лишиться зеленим.

    Шлях узятий той САМИЙ, який називає журнал претензій. Спершу тут стояв
    `reports/MUTATION_REPORT.json` — і це була помилка того ж роду, що й уся ця правка:
    той файл кладе `snapshot_assurance`, а `make mutation` його не торкається, тож
    твердження описувало б не той артефакт, який цитує претензія.
    """
    import json

    from korpus.application.release_claims import claim_ledger

    cited = {
        claim["evidence"]
        for claim in claim_ledger(ROOT, "0" * 64, "v0.9.7")["claims"]
        if claim["id"] == "CLM-MUTATION"
    }
    assert cited == {"reports/MUTATION_FULL_CATALOGUE_CURRENT.json"}, cited
    report = json.loads((ROOT / cited.pop()).read_text(encoding="utf-8"))
    assert "status" in report, "артефакт, який цитує претензія, не оголошує вироку"
    assert report["status"] in {"PASS", "FAIL"}


def _probe_exit_code(statuses: dict[str, str]) -> int:
    """Прогнати РЕАЛЬНИЙ `_run_probe` із підставленими результатами мутантів.

    Пишемо лише в пам'ять: звіт і друк заглушені, бо предмет тут — КОД ПОВЕРНЕННЯ,
    а не артефакт.
    """
    import run_mutation_tests as runner

    chosen = [runner.MUTANTS[index].id for index in range(len(statuses))]
    plan = dict(zip(chosen, statuses.values(), strict=True))

    def selected(mutants: object, jobs: int) -> list[dict[str, object]]:
        return [
            {
                "id": mutant.id,
                "file": mutant.file,
                "status": plan[mutant.id],
                "target_occurrences": 0 if plan[mutant.id] == "INVALID" else 1,
                "tests": list(mutant.tests),
            }
            for mutant in mutants  # type: ignore[attr-defined]
        ]

    original = (runner.run_selected, runner._write_report, runner._print_summary)
    runner.run_selected = selected  # type: ignore[assignment]
    runner._write_report = lambda *a, **k: None  # type: ignore[assignment]
    runner._print_summary = lambda report: None  # type: ignore[assignment]
    try:
        return runner._run_probe(",".join(chosen), 1)
    finally:
        runner.run_selected, runner._write_report, runner._print_summary = original


def test_the_probe_exit_code_is_the_declared_verdict_not_a_second_opinion() -> None:
    """ВИМІРЯНО 04.09.2026. Звіт казав FAIL, оболонка чула 0.

    `mutation_score` ділить убитих на ЗАСТОСОВНИХ. Мутант, чию ціль забрав рефакторинг,
    виходить із знаменника РАЗОМ із чисельником, тож {убитий, ціль_втрачена} дає рівно
    1.0 — і колишній код повернення проби виводив «пройшло» саме з цього числа. Тобто
    інструмент, яким перевіряють «чи не роззброїв мій рефакторинг мутанта», мовчав
    рівно в тому випадку, заради якого його й запускають: M550, M551 і M552 втратили
    цілі 04.09.2026 після винесення функцій у `check_dormant_subsystems`.

    Твердження тут не про число, а про ТОТОЖНІСТЬ: код повернення мусить бути тим
    самим вироком, який звіт оголошує, а не другою думкою про ті самі дані.
    """
    assert _probe_exit_code({"a": "KILLED", "b": "INVALID"}) == 1


def test_a_probe_of_killed_mutants_exits_zero() -> None:
    """Плече, чиє завдання — пройти: без нього попереднє твердження тримала б константа."""
    assert _probe_exit_code({"a": "KILLED", "b": "KILLED"}) == 0


def test_a_surviving_mutant_fails_the_probe() -> None:
    assert _probe_exit_code({"a": "KILLED", "b": "SURVIVED"}) == 1


def test_an_errored_mutant_fails_the_probe() -> None:
    """ERROR так само виходить зі знаменника — той самий механізм, інша назва."""
    assert _probe_exit_code({"a": "KILLED", "b": "ERROR"}) == 1
