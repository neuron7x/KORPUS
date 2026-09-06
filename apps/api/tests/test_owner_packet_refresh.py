"""Виробник виміряних блоків пакета власника не мав жодного тесту.

`refresh_owner_packet.py --check` — єдине, що ловить розбіжність пакета з артефактами
ДО того, як власник прочитає число (`source_bound` бачить лише дайджест, а не те, чи
числа під ним про це дерево). Обидва засіяні в ньому мутанти вижили на повній
батареї d41b12f1: інвертований вирок `--check` і невиконуваний `__main__`.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/refresh_owner_packet.py"
SPEC = importlib.util.spec_from_file_location("refresh_owner_packet", SCRIPT)
assert SPEC and SPEC.loader
REFRESH = importlib.util.module_from_spec(SPEC)
sys.modules["refresh_owner_packet"] = REFRESH
SPEC.loader.exec_module(REFRESH)

DIGEST = "a" * 64
LOAD = {
    "cold_first_request": {"status": 200, "seconds": 1.5},
    "load": {
        "concurrency": 4,
        "requests": 40,
        "p50_seconds": 0.1,
        "p95_seconds": 0.2,
        "statuses": {"200": 40},
    },
    "soak": {
        "concurrency": 2,
        "requests": 60,
        "p50_seconds": 0.1,
        "p95_seconds": 0.3,
        "statuses": {"200": 60},
    },
    "spike": {
        "concurrency": 8,
        "requests": 20,
        "p50_seconds": 0.2,
        "p95_seconds": 0.9,
        "statuses": {"200": 20},
    },
}
RECOVERY = {
    "rto_seconds": 12.0,
    "restore_seconds": 8.0,
    "verify_seconds": 4.0,
    "rpo_seconds": 0.0,
    "lost_events": 0,
    "scale_class": "pilot",
}
REGISTRY = {
    "counts": {"internal": 0, "external": 7},
    "generated_at": "2026-09-06T17:20:33+00:00",
    "source_tree_sha256": "0be621c1f1dcd1c9" + "0" * 48,
}
PREDICATES = {
    "software_ready": 7,
    "predicates_total": 14,
    "states": [
        {"id": "live_scanners", "blocks_candidate": True, "externally_satisfied": False},
        {"id": "closed", "blocks_candidate": False, "externally_satisfied": True},
    ],
}

PACKET_TEMPLATE = """# Пакет власника

**ДАЙДЖЕСТ ДЖЕРЕЛА:** `{digest}`

| фаза | конкурентність | запити | p50 | p95 | коди |
| холодний перший | 1 | 1 | — | — | {cold} |
| навантаження | 4 | 40 | 0,100 | 0,200 | 40×200 |
| **soak (за ним судять SLO)** | 2 | 60 | 0,100 | 0,300 | 60×200 |
| сплеск | 8 | 20 | 0,200 | 0,900 | 20×200 |

RTO **12,000 с** (відновлення 8,000 + перевірка 4,000) · RPO **0,000 с**\
 · втрачено подій 0 · клас масштабу `pilot`.

### 2.6-BIS Стан блокерів (вимір 2026-09-06, дайджест `0be621c1f1dcd1c9`)

`software_ready` **7 із 14**. Реєстр блокерів: **external** 7 · **internal** 0.

`blocks_candidate` **1** · зовнішніх вимог **1 із 2**. Блокують: `live_scanners`.
"""
IN_SYNC = PACKET_TEMPLATE.format(digest=DIGEST, cold="200 за **1,500 с** (стеля 5,0)")


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name, payload in (
        ("load-probe.json", LOAD),
        ("recovery-report.json", RECOVERY),
        ("BLOCKER_REGISTRY.json", REGISTRY),
        ("PRODUCTION_HARD_PREDICATES.json", PREDICATES),
    ):
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(REFRESH, "ROOT", tmp_path)
    monkeypatch.setattr(REFRESH, "PACKET", tmp_path / "OWNER_PILOT_RELEASE_PACKET.md")
    monkeypatch.setattr(REFRESH, "LOAD", tmp_path / "load-probe.json")
    monkeypatch.setattr(REFRESH, "RECOVERY", tmp_path / "recovery-report.json")
    monkeypatch.setattr(REFRESH, "REGISTRY", tmp_path / "BLOCKER_REGISTRY.json")
    monkeypatch.setattr(REFRESH, "PREDICATES", tmp_path / "PRODUCTION_HARD_PREDICATES.json")
    monkeypatch.setattr(REFRESH, "compute_source_digest", lambda _root: DIGEST)
    return tmp_path


def _check(tree: Path, text: str, monkeypatch: pytest.MonkeyPatch) -> tuple[int, dict[str, object]]:
    REFRESH.PACKET.write_text(text, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["refresh", "--check"])
    import contextlib
    import io

    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        code = REFRESH.main()
    return code, json.loads(captured.getvalue())


def test_a_packet_that_agrees_with_its_artefacts_passes(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, report = _check(tree, IN_SYNC, monkeypatch)
    assert code == 0
    assert report["status"] == "PASS"


def test_a_packet_whose_digest_drifted_is_refused(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Саме та розбіжність, заради якої `--check` існує: власник читає число про
    інше дерево, а `source_bound` цього не бачить."""
    code, report = _check(tree, IN_SYNC.replace(DIGEST, "b" * 64), monkeypatch)
    assert code == 1
    assert report["status"] == "FAIL"


def test_a_packet_whose_measured_number_drifted_is_refused(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, report = _check(tree, IN_SYNC.replace("RTO **12,000 с**", "RTO **3,000 с**"), monkeypatch)
    assert code == 1
    assert report["status"] == "FAIL"


def test_a_missing_anchor_is_named_not_silently_skipped(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Якір, якого немає, — це «блок не оновлено», а не «оновлено правильно»."""
    REFRESH.PACKET.write_text(IN_SYNC.replace("RTO **12,000 с**", "RTO 12 s"), encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        REFRESH.render(REFRESH.PACKET.read_text(encoding="utf-8"))
    assert "числа відновлення" in str(error.value)


def test_a_name_from_the_registry_that_looks_like_a_backreference_is_written_literally(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    r"""`re.sub` розгортає \1 і \g<...> У РЯДКУ ЗАМІНИ, а рядок заміни тут склеєно
    з ДАНИХ: імена лічильників приходять із BLOCKER_REGISTRY.json.

    `_constant` існує саме проти цього, і плече мусить стояти на РОБОЧОМУ шляху:
    тест, який кличе `_constant` напряму, лишається зеленим, коли виклик прибрано
    з `render`.
    """
    (tree / "BLOCKER_REGISTRY.json").write_text(
        json.dumps({"counts": {"external": 7, "\\g<0>": 1}}), encoding="utf-8"
    )
    rendered = REFRESH.render(IN_SYNC)
    assert "**\\g<0>** 1" in rendered, rendered[-400:]


def test_running_the_script_actually_runs_it() -> None:
    """`if __name__ == "__main__"` — теж твердження. Інвертоване, воно робить
    виробника мовчазним: жодного виводу, код виходу нуль, пакет не оновлено."""
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": f"{ROOT}/apps/api/src"},
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "--check" in done.stdout, done.stdout


def test_the_candidate_counter_has_a_producer(tmp_path: Path) -> None:
    """Число блокерів кандидата жило в §3 ЧОТИРМА написаннями від руки.

    Документ казав «блокерів кандидата НУЛЬ» на рядку 31 і 150, і «доки блокерів §3
    п'ять» на рядку 241 — суперечність у межах одного файла, при `make release-freeze`,
    що відмовляв. `source_bound` цього не бачив за побудовою: він ловить дрейф
    ДАЙДЖЕСТА, а не дрейф ТВЕРДЖЕННЯ на однаковому дайджесті.
    """
    predicates = {
        "states": [
            {"id": "a", "blocks_candidate": True, "externally_satisfied": False},
            {"id": "b", "blocks_candidate": False, "externally_satisfied": True},
        ]
    }
    line = REFRESH.candidate_line(predicates)
    assert "**1**" in line
    assert "`a`" in line and "`b`" not in line
    assert "1 із 2" in line


def test_no_blocking_predicate_says_so_in_words_not_by_silence() -> None:
    """Порожній перелік мусить читатись як «жодного», а не як відсутній рядок."""
    line = REFRESH.candidate_line({"states": [{"id": "a", "externally_satisfied": True}]})
    assert "**0**" in line
    assert "жодного" in line


def test_the_generated_blocker_block_carries_its_own_provenance() -> None:
    """Число оновлювалось, а дата й дайджест під ним — ні.

    Проліт починався з `software_ready`, тож заголовок над ним лишався зі штампом
    чужого дерева, і найсвіжіший вимір стояв підписаний чужим дайджестом.
    """
    registry = {
        "counts": {"CLOSED_ANCHORED": 6},
        "generated_at": "2026-09-06T17:20:33+00:00",
        "source_tree_sha256": "0be621c1f1dcd1c9" + "0" * 48,
    }
    block = REFRESH.blocker_line(registry, {"software_ready": 14, "predicates_total": 14})
    assert block.startswith("### 2.6-BIS")
    assert "2026-09-06" in block
    assert "0be621c1f1dcd1c9" in block
    assert REFRESH.BLOCKER_BLOCK.match(block), "згенерований блок не збігається з власним якорем"
