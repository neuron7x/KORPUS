"""Дайджест джерела мусить бути ОДИН і той самий там, де git є, і там, де його немає.

Функція фільтрувала обхід за `git ls-files`, а без git фільтр вимикався МОВЧКИ. Докстрінг
називав засновку прямо: «архів не має незатрекованих файлів за побудовою, тож запасний
шлях надійний». Для розпакованого архіву це так. Для РОБОЧОГО ДЕРЕВА, змонтованого в
контейнер без git, — ні.

ВИМІРЯНО 02.09.2026 на тому самому дереві:

    хост       20475f9ea284f819…    1529 файлів
    контейнер  d92c01de22c1ced3…    1538 файлів

Дев'ять зайвих — `infra/secrets/*.txt`, незатрековані, у відкритому вигляді. Наслідок не
косметичний: гейт точного середовища зобов'язаний бігти в продакшенному образі, де git
відсутній ЗА ПОБУДОВОЮ, тож предикат `exact_python_3_12_13_environment` не міг бути
задоволений НІКОЛИ — і це читалось як брак роботи, а не як дефект виміру.
"""

from __future__ import annotations

import json
import subprocess

import pytest
from korpus.application import provenance


def _tree(root, *, tracked: list[str], untracked: list[str]) -> None:
    for name in (*tracked, *untracked):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n", encoding="utf-8")
    (root / "SOURCE_MANIFEST.json").write_text(
        json.dumps({"files": [{"path": name} for name in tracked]}), encoding="utf-8"
    )


def test_the_manifest_answers_what_git_would_have_answered(tmp_path, monkeypatch):
    _tree(tmp_path, tracked=["scripts/a.py"], untracked=["scripts/secret.txt"])
    monkeypatch.setattr(
        provenance.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("git absent"))
    )
    assert provenance._tracked_paths(tmp_path) == frozenset({"scripts/a.py"})


def test_an_untracked_file_does_not_enter_the_digest_when_git_is_absent(tmp_path, monkeypatch):
    """Саме цей випадок і давав різні числа: без git секрети потрапляли у вимір.

    Порівнюються ДВА ДЕРЕВА з однаковим відстеженим вмістом і різними незатрекованими
    файлами. Перша версія цього тесту порівнювала два ПРОГОНИ на одному дереві — і
    мутант, що вимикав запасне джерело, ВИЖИВАВ: у тимчасовій теці git недоступний в
    обох гілках, тож обидві мінялись однаково й різниці не було. Тест, чиї два плеча
    рухаються разом, не розрізняє нічого.
    """
    monkeypatch.setattr(
        provenance.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("git absent"))
    )
    clean = tmp_path / "clean"
    dirty = tmp_path / "dirty"
    _tree(clean, tracked=["scripts/a.py"], untracked=[])
    _tree(dirty, tracked=["scripts/a.py"], untracked=["infra/secrets/jwt.txt"])

    assert provenance.compute_source_digest(
        clean, ["scripts", "infra"]
    ) == provenance.compute_source_digest(dirty, ["scripts", "infra"]), (
        "незатрекований файл змінив дайджест — обсяг виміру залежить від сміття в дереві"
    )


def test_a_tree_with_neither_git_nor_manifest_has_an_unknown_scope(tmp_path, monkeypatch):
    """None означає «обсяг невідомий», а не «обсяг дорівнює всьому»."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/a.py").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(
        provenance.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("git absent"))
    )
    assert provenance._tracked_paths(tmp_path) is None


@pytest.mark.parametrize(
    "payload",
    ["{не json", json.dumps({"files": "не список"}), json.dumps({}), json.dumps({"files": []})],
    ids=["битий json", "files не список", "без files", "порожній files"],
)
def test_an_unusable_manifest_is_not_read_as_an_empty_tracked_set(tmp_path, payload):
    """Порожня множина відстежених виключила б УСЕ — тихо й повністю."""
    (tmp_path / "SOURCE_MANIFEST.json").write_text(payload, encoding="utf-8")
    assert provenance._manifest_paths(tmp_path) is None


def test_git_still_wins_when_it_can_answer(tmp_path):
    """Маніфест — ДРУГЕ джерело: він виключає сам себе, git — ні."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.py"], check=True)
    (tmp_path / "SOURCE_MANIFEST.json").write_text(
        json.dumps({"files": [{"path": "інше.py"}]}), encoding="utf-8"
    )
    assert provenance._tracked_paths(tmp_path) == frozenset({"a.py"})
