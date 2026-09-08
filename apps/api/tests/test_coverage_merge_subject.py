"""Обʼєднання покриття двох діалектів мусить описувати ОДНЕ дерево.

Злиття зіставляє гілки за (файл, дуга), а дуга — пара НОМЕРІВ РЯДКІВ. Прогони, зняті на
різних деревах, дають випадкові збіги: зсунутий код потрапляє під стару дугу і
зараховується як покритий. Помилка йде в небезпечний бік — покриття ЗАВИЩУЄТЬСЯ, а
ратчет читає саме це число.

Виміряно 08.09.2026: `var/coverage-postgres.json` був знятий 06.09, до злиття керованого
шару спроможностей. Обʼєднання з ним давало 233 непокриті гілки; після перезняття
PostgreSQL на цьому ж дереві — 247. Чотирнадцять «покритих» гілок існували лише як збіг
номерів рядків.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

import sys  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))

from merge_dialect_coverage import same_subject  # noqa: E402


def _report(files: dict[str, int]) -> dict[str, object]:
    return {
        "files": {
            path: {"summary": {"num_statements": count}, "missing_branches": []}
            for path, count in files.items()
        }
    }


def test_two_runs_of_the_same_tree_are_merged() -> None:
    """Негативний контроль: сторож карає РОЗБІЖНІСТЬ, а не саме злиття."""
    tree = _report({"a.py": 10, "b.py": 4})
    assert same_subject(tree, json.loads(json.dumps(tree))) is None


def test_a_file_present_in_only_one_run_refuses_the_merge() -> None:
    assert same_subject(_report({"a.py": 10, "b.py": 4}), _report({"a.py": 10})) is not None


def test_a_file_whose_statement_count_moved_refuses_the_merge() -> None:
    """Та сама назва файла з іншою кількістю тверджень — інший файл.

    Саме цей випадок і стався: модуль виріс, номери рядків зсунулись, і старі дуги
    почали влучати в інший код.
    """
    reason = same_subject(_report({"a.py": 10}), _report({"a.py": 11}))
    assert reason is not None and "тверджень" in reason


def test_the_real_dialect_reports_describe_one_tree() -> None:
    """Той самий сторож на СПРАВЖНІХ файлах: інакше правило живе лише на синтетиці."""
    primary, secondary = ROOT / "var/coverage.json", ROOT / "var/coverage-postgres.json"
    if not primary.is_file() or not secondary.is_file():
        return
    assert (
        same_subject(
            json.loads(primary.read_text(encoding="utf-8")),
            json.loads(secondary.read_text(encoding="utf-8")),
        )
        is None
    )
