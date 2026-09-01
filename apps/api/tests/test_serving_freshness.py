"""Звіт, отриманий від живого сервера, кредитує ПРОЦЕС, а не дерево.

П'ять осей профілю міряються запитом до сервера. Звіт із застарілим КОРПУСОМ ловиться
ідентичністю входів; звіт із застарілим ПРОЦЕСОМ не ловиться нічим — корпус той самий,
вимірювач той самий, вік малий, а відповідав інший код.

Виміряно 01.09.2026: усі п'ять обслуговуючих процесів були старші за найновіший файл
коду, включно з тим, що обслуговує читача. Один із них до того ж віддавав HTTP 500 на
кожне питання від попереднього дня, бо ліниво імпортований модуль підтягнувся вже після
правки сигнатури — в одному процесі жили дві ревізії.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from check_serving_freshness import adjudicate, newest_source, serving_processes  # noqa: E402

NOW = datetime.now(UTC).timestamp()


def _process(pid: str, offset: float) -> dict[str, object]:
    return {
        "pid": pid,
        "port": 8000,
        "started_at": "",
        "started_epoch": NOW + offset,
        "command": "uvicorn",
    }


def test_a_process_older_than_the_code_does_not_serve_the_tree() -> None:
    verdict = adjudicate([_process("1", -60)], (NOW, "retrieval.py"))

    assert verdict["rate"] == 0.0
    assert verdict["stale"] == ["1"]


def test_a_process_started_after_the_last_edit_does() -> None:
    """Негативний контроль: гейт, що не приймає нічого, не є гейтом."""
    assert adjudicate([_process("1", +60)], (NOW, "retrieval.py"))["rate"] == 1.0


def test_one_stale_worker_is_enough_to_lose_the_claim() -> None:
    """Читача обслуговують кілька процесів; свіжий серед старих нічого не рятує."""
    verdict = adjudicate([_process("1", -60), _process("2", +60)], (NOW, "retrieval.py"))

    assert verdict["rate"] == 0.5


def test_no_serving_process_is_unknown_rather_than_agreement() -> None:
    """Вимкнений сервер не сміє робити профіль зеленим."""
    verdict = adjudicate([], (NOW, "retrieval.py"))

    assert verdict["status"] == "UNKNOWN"
    assert verdict["rate"] is None


def test_discovery_takes_a_process_that_opened_a_corpus(tmp_path: Path) -> None:
    """Ознака — відкрита база доказів, не перелік у конфізі, який розійшовся б мовчки."""
    entry = tmp_path / "4242"
    entry.mkdir()
    (entry / "environ").write_bytes(b"PATH=/usr/bin\x00KORPUS_DATABASE_URL=sqlite:////srv/k.db\x00")
    (entry / "cmdline").write_bytes(b"python\x00-m\x00uvicorn\x00--port\x008000\x00")

    found = serving_processes(tmp_path)

    assert [item["pid"] for item in found] == ["4242"]
    assert found[0]["port"] == 8000


def test_a_process_that_opened_no_corpus_is_not_serving(tmp_path: Path) -> None:
    """Негативний контроль: виявлення, у яке потрапляє все, нічого не виявляє."""
    entry = tmp_path / "77"
    entry.mkdir()
    (entry / "environ").write_bytes(b"PATH=/usr/bin\x00KORPUS_ENVIRONMENT=local\x00")
    (entry / "cmdline").write_bytes(b"python\x00-m\x00pytest\x00")

    assert serving_processes(tmp_path) == []


def test_the_newest_source_is_the_one_the_server_would_have_to_hold() -> None:
    """Порівнюється з КОДОМ застосунку, не з деревом: правка звіту не вимагає перезапуску."""
    stamp, path = newest_source()

    assert stamp > 0
    assert path.startswith("apps/api/src/")
