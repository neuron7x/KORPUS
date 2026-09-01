"""Покриття гейтами — саме воно тепер під гейтом.

Виміряно 31.08.2026 на цьому Makefile: 193 цілі, з них під `check` виконуються 44;
перевірочних цілей 44, і 27 не виконуються ЖОДНОЮ дорогою. Три з них того ж дня
перевірили руками — усі три червоні. Тобто речення «дерево зелене» було твердженням
про підмножину, якої ніхто не перелічив.

Тести тримають не список із 27 (він мусить порожніти), а ЧОТИРИ властивості:
покриття міряється виконанням скрипта, а не досяжністю цілі; нова діра червонить;
мертвий і примарний винятки червонять теж; і сам гейт покриття стоїть під гейтом.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/verify_gate_closure.py"
REGISTRY = ROOT / "config/operations/gate-closure.json"
SPEC = importlib.util.spec_from_file_location("verify_gate_closure", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


def _real() -> tuple[dict[str, set[str]], list[str], dict[str, set[str]]]:
    return GATE.parse_graph((ROOT / "Makefile").read_text(encoding="utf-8"))


# ------------------------------------------------- покриття = виконання, не досяжність


def test_a_target_whose_script_another_target_runs_is_not_a_gap() -> None:
    """Найдорожча помилка цього гейта — оголосити дірою те, що закрите.

    `validate` виконує `scripts/validate_infrastructure.py` і
    `scripts/validate_kubernetes.py` прямо в рецепті, а цілі `infra-validate` і
    `kubernetes-validate` роблять рівно те саме. Перевірка, що дивиться лише на граф
    цілей, зажадала б для них виправдання — і реєстр почав би описувати вигадані діри.
    """
    edges, _declared, scripts = _real()
    covered = GATE.enforced(edges, scripts)
    for target in ("infra-validate", "kubernetes-validate"):
        assert target in covered, f"{target} оголошено дірою, хоча його скрипт виконується"


def test_reachability_alone_would_call_those_targets_gaps() -> None:
    """Дуал до попереднього: без обліку скриптів вони СПРАВДІ виглядають дірами.

    Без цього твердження перший тест був би сумісний із гейтом, який просто нічого не
    перевіряє: він мусить показати, що різниця між двома означеннями існує.
    """
    edges, _declared, _scripts = _real()
    bare = GATE.reachable(edges, GATE.ROOTS)
    assert "infra-validate" not in bare and "kubernetes-validate" not in bare


def test_recipe_edges_count_as_reachability() -> None:
    """`evidence-refresh` кличе `$(MAKE) dependency-locks` у рецепті, не в заголовку."""
    edges, _declared, _scripts = _real()
    assert "dependency-locks" in edges.get("evidence-refresh", set())


# --------------------------------------------------------- три способи збрехати


def _verdict(makefile: str, registry: dict) -> str:
    edges, declared, scripts = GATE.parse_graph(makefile)
    return GATE.verdict(GATE.assess(edges, declared, registry, scripts, makefile))


def test_a_new_unwired_verification_target_reddens_on_the_real_makefile() -> None:
    """Негативний контроль проти РЕАЛЬНОСТІ, не проти синтетики."""
    poisoned = (ROOT / "Makefile").read_text(encoding="utf-8") + (
        "\nsomething-new-verify:\n\t$(PY) scripts/nothing.py\n"
    )
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert _verdict(poisoned, registry) == "FAIL"


def test_an_exemption_for_something_already_enforced_reddens() -> None:
    """Мертвий виняток бреше не менше за відсутній: він каже, що діра є, коли її нема."""
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry["accepted"].append(
        {"target": "module-budget", "class": "accepted_red", "reason": "x" * 40, "on": "2026-08-31"}
    )
    assert _verdict((ROOT / "Makefile").read_text(encoding="utf-8"), registry) == "FAIL"


def test_an_exemption_for_a_target_that_no_longer_exists_reddens() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry["accepted"].append(
        {"target": "gone-verify", "class": "not_a_gate", "reason": "y" * 40, "on": "2026-08-31"}
    )
    assert _verdict((ROOT / "Makefile").read_text(encoding="utf-8"), registry) == "FAIL"


# ---------------------------------------------------- гейт покриття сам під гейтом


def test_the_closure_gate_is_itself_reached_by_check() -> None:
    """Гейт про покриття гейтами, який сам не під гейтом, спростовує себе першим рядком."""
    edges, _declared, scripts = _real()
    assert "gate-closure" in GATE.enforced(edges, scripts)


def test_the_real_tree_has_no_unregistered_gap() -> None:
    """Стан репозиторію, а не синтетика: кожна діра або закрита, або названа."""
    edges, declared, scripts = _real()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    findings = GATE.assess(edges, declared, registry, scripts, text)
    assert GATE.verdict(findings) == "PASS", findings


def test_every_accepted_gap_names_a_reason_and_a_date() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for entry in registry["accepted"]:
        assert len(entry["reason"].strip()) >= 20, entry["target"]
        assert entry["on"] == "2026-08-31" or len(entry["on"]) == 10, entry["target"]


def test_unknown_is_never_a_pass() -> None:
    assert _verdict("", {"accepted": []}) == "UNKNOWN"
    assert _verdict("span-hygiene:\n\tone\n", {"accepted": []}) == "UNKNOWN"


def test_gate_reddens_on_every_defect_separately() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--selftest"], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


# ------------------------------------------- дві властивості САМОГО Makefile


def test_a_duplicated_target_reddens_on_the_real_makefile() -> None:
    """Виміряно 01.09.2026: `fetch-stubs` мав два визначення.

    Виконувалось останнє — і воно вийшло сильнішим ВИПАДКОВО. У зворотному порядку
    ціль ходила б без `--database`, тобто не дивилась би на обслуговуваний корпус і
    лишалась зеленою. make лише попереджає, код виходу не міняється, тож ніхто не
    читає. Пор. те саме з дубльованим ім'ям джоба в CI.
    """
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert GATE.duplicate_recipes(text) == []
    poisoned = text + "\nspan-hygiene:\n\t@echo друге визначення\n"
    assert GATE.duplicate_recipes(poisoned) == ["span-hygiene"]
    assert _verdict(poisoned, json.loads(REGISTRY.read_text(encoding="utf-8"))) == "FAIL"


def test_a_second_header_without_a_recipe_is_legal() -> None:
    """Розділене оголошення передумов — звичайний make і НЕ мовчазне перекриття."""
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert GATE.duplicate_recipes(text + "\nspan-hygiene: api-test\n") == []


def test_the_reason_requires_argument_is_itself_checked() -> None:
    """Причина в реєстрі — теж твердження, і його ніхто не перевіряв.

    `requires_argument` каже «без аргументу не запуститься». Якщо в рецепті кожна
    змінна загорнута в `$(if ...)`, ціль запускається порожньою — виняток описує
    перешкоду, якої немає.
    """
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registry["accepted"].append(
        {
            "target": "load-probe",
            "class": "requires_argument",
            "reason": "z" * 40,
            "on": "2026-09-01",
        }
    )
    edges, declared, scripts = _real()
    findings = GATE.assess(edges, declared, registry, scripts, text)
    assert _finding_named(findings, "unfounded_requirement")["verdict"] == "FAIL"


def _finding_named(findings: list[dict[str, str]], check: str) -> dict[str, str]:
    """Конкретна перевірка, не сукупний вирок: інакше мутант ховається за сусідкою."""
    return next(item for item in findings if item["check"] == check)


def test_every_requires_argument_entry_names_a_variable_it_truly_needs() -> None:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    all_recipes = GATE.recipes(text)
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for entry in registry["accepted"]:
        if entry.get("class") != "requires_argument":
            continue
        assert GATE.mandatory_variables(all_recipes[entry["target"]]), entry["target"]


def test_a_variable_only_inside_an_if_is_not_a_requirement() -> None:
    assert GATE.mandatory_variables(['\t$(PY) x.py $(if $(A),--a "$(A)")']) == set()
    assert GATE.mandatory_variables(['\t$(PY) x.py --a "$(A)"']) == {"A"}
    assert GATE.mandatory_variables(['\t@test -n "$(A)" || exit 2']) == {"A"}
    assert GATE.mandatory_variables(['\t$(PY) x.py --a "$(or $(A),$(SERVED_CORPUS))"']) == set()


def test_not_measured_is_not_a_pass_and_not_an_accusation() -> None:
    """Без тексту Makefile покриття не обчислюється повністю — і це UNKNOWN.

    Не FAIL: знижку для цілей, чия робота — самоперевірка, дає `selftest_only`, і без
    неї три законні цілі виглядали б дірами. Оголосити їх дірами означало б звинуватити
    за брак ВЛАСНОГО входу гейта.
    """
    edges, declared, scripts = _real()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    findings = GATE.assess(edges, declared, registry, scripts)
    assert GATE.verdict(findings) == "UNKNOWN"
    assert findings[0]["check"] == "gate_closure"


# ------------------------------------------- безпека пакета, який ми самі роздаємо


def test_the_packaging_lane_checks_the_archive_it_produces() -> None:
    """`zip_safety.py` існував із тестами і ніколи не дивився на НАШ зіп.

    Ціль `zip-safety-verify` вимагала ARCHIVE, а шлях архіву не був відомий жодному
    лану — тож перевірка на zip-slip, симлінки й бомби стиснення жила поруч із
    пакувальником і не була до нього під'єднана. Тепер ім'я архіву приходить із
    `dist/LATEST`, яке пише сам пакувальник: одне джерело імені, не друга копія.
    """
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = "\n".join(GATE.recipes(text)["package"])
    assert "scripts/zip_safety.py" in recipe
    assert "dist/LATEST" in recipe

    script = (ROOT / "scripts/package_repository.sh").read_text(encoding="utf-8")
    assert '> "dist/LATEST"' in script, "пакувальник мусить називати архів у одному місці"


def test_zip_safety_is_no_longer_an_accepted_gap() -> None:
    edges, _declared, scripts = _real()
    assert "zip-safety-verify" in GATE.enforced(edges, scripts)
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert all(entry["target"] != "zip-safety-verify" for entry in registry["accepted"])


# ------------------------------- ціль, чия робота — самоперевірка, і хто її виконує


def test_the_classifier_sees_axis_and_store_shaped_names() -> None:
    """Класифікатор за іменем не бачив власних нових гейтів.

    `evidence-stores`, `corpus-axes`, `answer-axes`, `selftest-coverage` не містять
    жодного слова зі старого правила, тож ніщо не змушувало б їх лишатись підключеними:
    відключи — і `unregistered_gap` промовчав би. Ціна розширення асиметрична свідомо.
    """
    for name in ("evidence-stores", "corpus-axes", "answer-axes", "selftest-coverage"):
        assert GATE.VERIFICATION.search(name), name


def test_a_target_that_only_runs_a_selftest_is_covered_by_the_selftest_gate() -> None:
    """`selftest-coverage` знаходить скрипти сам, тож у його рецепті їх НЕМАЄ.

    Побачити покриття через перелік скриптів у рецепті тому неможливо, і виняток у
    реєстрі був би твердженням, якого ніхто не переміряє. Правило обчислюється.
    """
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    only = GATE.selftest_only(text)
    for name in ("public-surface-selftest", "capture-evidence-selftest", "recheck-blocked-selftest"):
        assert name in only, name
    assert "check" not in only and "validate" not in only


def test_a_target_that_does_more_than_a_selftest_is_not_covered_for_free() -> None:
    """Інакше будь-яка ціль, що ЗАОДНО кличе самоперевірку, ставала б закритою."""
    only = GATE.selftest_only(
        "a:\n\t$(PY) x.py --selftest\n"
        "b:\n\t$(PY) x.py --selftest\n\t$(PY) x.py --database d\n"
    )
    assert only == {"a"}


def test_the_selftest_shortcut_needs_the_selftest_gate_to_be_covered() -> None:
    """Якщо `selftest-coverage` випаде з `validate`, знижка мусить зникнути разом із ним."""
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    without = text.replace("validate: public-env-parity gate-closure selftest-coverage",
                           "validate: public-env-parity gate-closure")
    assert "selftest-coverage" not in without.splitlines()[
        next(i for i, line in enumerate(without.splitlines()) if line.startswith("validate:"))
    ]
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    edges, declared, scripts = GATE.parse_graph(without)
    findings = GATE.assess(edges, declared, registry, scripts, without)
    gap = _finding_named(findings, "unregistered_gap")
    # Конкретика, не сукупний вирок: без неї мутант ховається за тим, що сам
    # `selftest-coverage` теж стає дірою, і гейт червоніє з іншої причини.
    assert gap["verdict"] == "FAIL"
    for name in ("public-surface-selftest", "capture-evidence-selftest"):
        assert name in gap["detail"], gap["detail"]
