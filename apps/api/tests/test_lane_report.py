"""«Зелено, крім однієї» і «одна червона, про решту не відомо» — протилежні твердження.

`make` спиняється на першій відмові. Виміряно 01.09.2026: `validate` падав на ТРЕТІЙ цілі
з тридцяти, повідомлення називало одну проблему, і 26 цілей не виконувались узагалі. Код
виходу не розрізняє «26 зелених» від «26 невиміряних», а `make -k` дає лише два стани й
не має третього — ціль, до якої не дійшли, у ньому не відрізняється від відсутньої.

Тому первинне число цього звіту — `not_run`, і тести стережуть саме його.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from run_lane import FAILED, NOT_RUN, PASSED, TIMED_OUT, lane_targets, summarise  # noqa: E402


def _result(state: str) -> dict[str, object]:
    return {"state": state, "code": 0 if state == PASSED else 1, "seconds": 0.1}


def test_a_target_never_reached_is_not_a_pass() -> None:
    verdict = summarise({"a": _result(FAILED), "b": _result(NOT_RUN)}, "l")

    assert verdict["passed"] == 0
    assert verdict["not_run_targets"] == ["b"]


def test_an_unreached_target_makes_the_lane_partial() -> None:
    """Лан із невиміряними цілями не описує лан — він описує його початок."""
    assert summarise({"a": _result(FAILED), "b": _result(NOT_RUN)}, "l")["status"] == "PARTIAL"


def test_a_lane_that_ran_everything_is_measured_even_when_red() -> None:
    """Червоний вимір — це вимір. Стан PARTIAL про якість цілей не каже нічого."""
    verdict = summarise({"a": _result(PASSED), "b": _result(FAILED)}, "l")

    assert verdict["status"] == "MEASURED"
    assert verdict["failed_targets"] == ["b"]


def test_a_timeout_is_neither_pass_nor_fail() -> None:
    """Ціль, що не вклалась, не дала вироку — інакше найдорожча перевірка найтихіша."""
    verdict = summarise({"a": _result(TIMED_OUT)}, "l")

    assert verdict["passed"] == 0
    assert verdict["failed"] == 0
    assert verdict["timed_out_targets"] == ["a"]


def test_the_target_list_comes_from_the_makefile(tmp_path: Path) -> None:
    """Копія переліку розійшлася б мовчки саме тоді, коли хтось додасть ціль."""
    makefile = tmp_path / "Makefile"
    makefile.write_text("lane-x: alpha beta gamma\n\techo hi\n", encoding="utf-8")

    assert lane_targets(makefile, "lane-x") == ["alpha", "beta", "gamma"]


def test_a_target_added_to_the_makefile_is_seen(tmp_path: Path) -> None:
    """Негативний контроль до попереднього: перелік мусить РУХАТИСЬ разом із деревом."""
    makefile = tmp_path / "Makefile"
    makefile.write_text("lane-x: alpha\n", encoding="utf-8")
    before = lane_targets(makefile, "lane-x")
    makefile.write_text("lane-x: alpha delta\n", encoding="utf-8")

    assert lane_targets(makefile, "lane-x") == [*before, "delta"]


def test_the_real_validate_lane_is_read_from_the_tree() -> None:
    targets = lane_targets(ROOT / "Makefile", "validate")

    assert len(targets) > 5
    assert "module-budget" in targets
    assert all("$" not in target for target in targets)


# ── Мутанти M530 і M532 пережили тести вище, і це показало справжню діру: вони стерегли
# ЗВЕДЕННЯ, а не бігун. Два найважливіші стани народжуються в `execute` і `run_target`,
# і саме там їх ніхто не перевіряв.


def test_a_timeout_is_recorded_as_a_timeout_by_the_runner_itself() -> None:
    """Не зведення, а сам запуск: гілка таймауту мусить давати власний стан."""
    from run_lane import run_target

    result = run_target("5", timeout=0.2, make="sleep")

    assert result["state"] == TIMED_OUT
    assert result["code"] is None


def test_a_target_the_runner_never_reached_stays_not_run_on_disk(tmp_path: Path) -> None:
    """Заповнення ДО прогону: обвал бігуна мусить лишати невиконані ВИДИМИМИ.

    Перелік, що дописується по ходу, зробив би їх невідрізненними від неоголошених —
    тобто найтихішою можливою відмовою. Обвал імітується підміною `run_target`, а не
    сигналом: проба, що вбиває власний прогін, вимірює не те, що обіцяє.
    """
    import json

    import run_lane

    makefile = tmp_path / "Makefile"
    makefile.write_text("lane-x: alpha beta gamma\n", encoding="utf-8")
    out = tmp_path / "lane.json"
    original = run_lane.run_target
    calls: list[str] = []

    def explode(target: str, timeout: float, make: str = "make") -> dict[str, object]:
        calls.append(target)
        if target == "beta":
            raise RuntimeError("бігун обвалився посеред лану")
        return {"state": PASSED, "code": 0, "seconds": 0.0}

    run_lane.run_target = explode
    try:
        with pytest.raises(RuntimeError):
            run_lane.execute("lane-x", timeout=5.0, out=out, makefile=makefile)
    finally:
        run_lane.run_target = original

    report = json.loads(out.read_text(encoding="utf-8"))

    assert calls == ["alpha", "beta"]
    assert report["detail"]["alpha"]["state"] == PASSED
    assert report["detail"]["gamma"]["state"] == NOT_RUN
    assert "gamma" in report["not_run_targets"]
    assert report["status"] == "PARTIAL"
