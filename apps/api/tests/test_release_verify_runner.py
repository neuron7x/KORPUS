from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/run_release_verify.py"
SPEC = importlib.util.spec_from_file_location("run_release_verify", SCRIPT)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def test_make_steps_bind_the_current_interpreter_without_splitting_spaces() -> None:
    assert RUNNER.make_command("api-test", "/tmp/korpus-venv/bin/python") == [
        "make",
        "api-test",
        "PY=/tmp/korpus-venv/bin/python",
    ]


def test_no_space_alias_preserves_the_active_virtual_environment() -> None:
    with RUNNER.interpreter_for_make() as executable:
        assert not any(char.isspace() for char in executable)
        completed = subprocess.run(
            [executable, "-c", "import pathlib,sys; print(pathlib.Path(sys.prefix).resolve())"],
            capture_output=True,
            text=True,
            check=True,
        )
    assert completed.stdout.strip() == str(Path(sys.prefix).resolve())


def test_a_spaced_interpreter_gets_an_alias_into_the_SAME_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Проба на ЗЛАМ, бо гілка з псевдонімом виконується лише при пробілі в шляху.

    Тест вище входить у `interpreter_for_make()` з тим інтерпретатором, який дала
    машина. Якщо в його шляху пробілів немає — а в чекауті CI їх немає, — функція
    повертається на першому ж рядку, гілка з псевдонімом не виконується ЖОДНОГО разу,
    і мутант M672 виживає, не змінивши нічого. Виміряно 03.09.2026: так він і вижив.
    Пробіл тут не гіпотеза: канонічне дерево цієї системи лежить у теці
    «Ядро основний проект Корпус», тож у продакшені гілка бере на себе кожен прогін,
    а вартувала її перевірка, яка спрацьовує лише поза CI.

    Псевдонім мусить вести в ТЕ САМЕ оточення. Вести його за `resolve()` означає
    піти за симлінком venv на системний інтерпретатор і мовчки покинути venv — make
    дістав би `/usr/bin/python` замість дерева, у якому міряють.
    """
    spaced = tmp_path / "з пробілом"
    spaced.mkdir()
    entry = spaced / Path(sys.executable).name
    entry.symlink_to(sys.executable)
    monkeypatch.setattr(RUNNER.sys, "executable", str(entry))

    with RUNNER.interpreter_for_make() as executable:
        assert not any(char.isspace() for char in executable), "псевдонім сам містить пробіл"
        completed = subprocess.run(
            [executable, "-c", "import pathlib,sys; print(pathlib.Path(sys.prefix).resolve())"],
            capture_output=True,
            text=True,
            check=True,
        )

    assert completed.stdout.strip() == str(Path(sys.prefix).resolve()), (
        "псевдонім вивів із активного venv"
    )


def _steps(*states: str) -> list[dict[str, object]]:
    return [{"target": f"t{index}", "state": state} for index, state in enumerate(states)]


def _accepted() -> dict[str, object]:
    """Вирок сторожа зведення дослівно: обсяг у назві, машинна відповідь — у полі."""
    return {"verdict": "BRANCH_CONSOLIDATION_ACCEPTED", "ACCEPTED": True, "problems": []}


def _rejected() -> dict[str, object]:
    return {"verdict": "REJECTED", "ACCEPTED": False, "problems": ["щось"]}


def test_a_scoped_acceptance_is_still_an_acceptance() -> None:
    """Сторож називає вирок ОБСЯГОМ; лан мусить читати поле, а не збіг рядка.

    Виміряно 03.09.2026: вісімнадцять кроків із вісімнадцяти пройшли, а лан сказав
    FAIL — споживач порівнював `verdict` з голим `ACCEPTED`, якого виробник більше не
    пише. Відмова була про код, якого немає.
    """
    assert RUNNER.status(_accepted(), _steps("PASSED", "PASSED")) == "PASS"


def test_a_verdict_without_the_acceptance_field_is_not_a_pass() -> None:
    """`NOT_REACHED` і `UNREADABLE` поля не несуть — і не сміють читатись як згода."""
    assert RUNNER.status({"verdict": "NOT_REACHED"}, _steps("PASSED", "PASSED")) == "FAIL"
    assert RUNNER.status({"verdict": "UNREADABLE"}, _steps("PASSED", "PASSED")) == "FAIL"
    assert RUNNER.status({"verdict": "BRANCH_CONSOLIDATION_ACCEPTED"}, _steps("PASSED")) == "FAIL"


def test_a_skipped_step_never_reads_as_a_pass() -> None:
    """Пропуск — третій стан, і зливати його з проходженням не можна.

    `assemble-assurance` вимагає доказу, який виробляє лише зовнішній лан, тож із
    --skip-external він не може пройти за побудовою. Поки станів було два, лан або
    спинявся на ньому назавжди, або — на дереві з давнім `var/recovery-report.json` —
    проходив, і вердикт залежав від вмісту var/, а не від виміру.
    """
    assert RUNNER.status(_accepted(), _steps("PASSED", "PASSED")) == "PASS"
    assert RUNNER.status(_accepted(), _steps("PASSED", RUNNER.SKIPPED)) == "INCOMPLETE"


def test_a_failure_outranks_a_skip() -> None:
    """FAIL перебиває все: інакше пропуск ховав би падіння сусіднього кроку."""
    assert RUNNER.status(_accepted(), _steps("FAILED", RUNNER.SKIPPED)) == "FAIL"
    assert RUNNER.status(_accepted(), _steps("TIMED_OUT", "PASSED")) == "FAIL"


def test_a_rejected_verdict_is_not_saved_by_a_full_run() -> None:
    """Усі кроки зелені й вирок відхилено — це FAIL, а не PASS через кроки."""
    assert RUNNER.status(_rejected(), _steps("PASSED", "PASSED")) == "FAIL"


def test_external_evidence_steps_are_named_not_guessed() -> None:
    """Перелік кроків, чий доказ зовнішній, мусить бути ОГОЛОШЕНИЙ і несуперечливий."""
    declared = {target for target, _ in RUNNER.STEPS}
    assert declared >= RUNNER.EXTERNAL_EVIDENCE, (
        "оголошено зовнішнім крок, якого в лані немає — реєстр розійшовся з ланом"
    )
    assert "assemble-assurance" in RUNNER.EXTERNAL_EVIDENCE
    assert "corpus-axes" in RUNNER.EXTERNAL_EVIDENCE, (
        "шість осей потребують живого API; відсутні звіти не можна назвати внутрішнім FAIL"
    )
