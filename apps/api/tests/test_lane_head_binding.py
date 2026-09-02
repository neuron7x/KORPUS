"""Звіт лану мусить називати дерево, яке міряв, — і розбіжність мусить бути FAIL.

До 02.09.2026 прив'язка була ГОДИННИКОМ: `ran_at < час коміту`. Годинник каже КОЛИ, а не
ЩО. Прогін, що почався до коміту й скінчився після нього, за часом свіжий; прогін на
брудному дереві за часом свіжий; прогін на іншій гілці з тим самим часом теж свіжий. І
розбіжність ішла в `unknown` — «не виміряно», хоча виміряно було ІНШЕ.

Тут прибито обидві половини: тотожність замість часу, і `problems` замість `unknown`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "verify_branch_consolidation", ROOT / "scripts/verify_branch_consolidation.py"
)
assert _spec is not None and _spec.loader is not None
verifier = importlib.util.module_from_spec(_spec)
sys.modules["verify_branch_consolidation"] = verifier
_spec.loader.exec_module(verifier)

HEAD = "a" * 40
DIGEST = "b" * 64


def _lane(**overrides: object) -> dict[str, object]:
    lane = {
        "passed": 31,
        "failed": 0,
        "not_run": 0,
        "ran_at": "2026-09-02T10:00:00+00:00",
        "source_commit": HEAD,
        "source_digest": DIGEST,
        "source_moved_during_run": False,
    }
    lane.update(overrides)
    return lane


def test_a_lane_measured_on_this_tree_is_bound():
    assert verifier.lane_binding_failure(_lane(), HEAD, DIGEST) is None


@pytest.mark.parametrize(
    ("overrides", "expect"),
    [
        ({"source_commit": "c" * 40}, "це різні дерева"),
        ({"source_digest": "d" * 64}, "дерево було брудне"),
        ({"source_commit": "", "source_digest": ""}, "не називає дерева"),
        ({"source_moved_during_run": True}, "зрушило ПІД ЧАС"),
    ],
    ids=["інший коміт", "брудне дерево", "без тотожності", "джерело зрушило"],
)
def test_every_way_of_being_about_another_tree_is_named(overrides, expect):
    reason = verifier.lane_binding_failure(_lane(**overrides), HEAD, DIGEST)
    assert reason is not None and expect in reason


def test_an_unbound_lane_is_a_problem_not_an_unknown():
    """`unknown` означає «не виміряно». Тут виміряно — просто НЕ ЦЕ дерево."""
    problems, unknown = verifier._lane_findings(
        _lane(source_commit="c" * 40), stale=False, binding="лан знято на ccccccc"
    )
    assert problems and not unknown, "розбіжність тотожності мусить бути FAIL, не UNKNOWN"


def test_the_clock_alone_would_have_passed_the_poisoned_report():
    """Негативний контроль на СТАРУ перевірку: без нього нова виглядала б зайвою.

    Звіт із майбутнім штампом і чужим комітом годинник пропускає, а прив'язка ловить.
    Саме цей випадок і був реальним failure mode, а не гіпотезою.
    """
    poisoned = _lane(source_commit="c" * 40, ran_at="2126-01-01T00:00:00+00:00")
    assert verifier.report_is_stale(str(poisoned["ran_at"]), head_epoch=0) is False
    assert verifier.lane_binding_failure(poisoned, HEAD, DIGEST) is not None


def test_the_runner_records_the_identity_it_measured():
    """Прив'язка недоказова, якщо її ніхто не пише: бігун мусить знімати тотожність."""
    runner = ROOT / "scripts/run_lane.py"
    source = runner.read_text(encoding="utf-8")
    assert "def tree_identity(" in source
    assert "source_moved_during_run" in source
    spec = importlib.util.spec_from_file_location("run_lane", runner)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_lane"] = module
    spec.loader.exec_module(module)
    identity = module.tree_identity(ROOT)
    assert len(identity["source_commit"]) == 40, "коміт не знято"
    assert len(identity["source_digest"]) == 64, "дайджест не знято"


def test_the_runner_sees_targets_reached_through_the_recipe():
    """Лан може складатися не з передумов, а з `$(MAKE) ціль` у рецепті.

    ВИМІРЯНО 02.09.2026: `check-nightly`, `corpus-axes` і `nightly-evidence` давали
    НУЛЬ цілей. Тобто інструмент, чиє єдине призначення — показати третій стан
    `NOT_RUN`, був сліпий саме до лану, що несе всі 16 осей відповіді. Порожній перелік
    читався б як «лан порожній», а не як «я його не бачу».

    `verify_gate_closure.parse_graph` читає ці ребра з 31.08 і має на них негативний
    контроль. Закон був записаний в одному інструменті й не поширився на сусідній.
    """
    import importlib.util
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    if str(root / "scripts") not in sys.path:
        sys.path.insert(0, str(root / "scripts"))
    spec = importlib.util.spec_from_file_location("lane_runner", root / "scripts/run_lane.py")
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runner
    spec.loader.exec_module(runner)

    makefile = root / "Makefile"
    for lane in ("check-nightly", "nightly-evidence"):
        assert runner.lane_targets(makefile, lane), (
            f"{lane}: бігун знову не бачить цілей, досяжних через рецепт"
        )
    # Негативний контроль на сам розбір: передумови й ребра рецепта — різні джерела,
    # і жодне з них не сміє поглинути інше.
    assert len(runner.lane_targets(makefile, "validate")) > 30, "передумови зникли"
