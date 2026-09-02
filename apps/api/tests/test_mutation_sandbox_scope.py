"""Пісочниця мутацій копіює ВІДСТЕЖЕНЕ дерево, а не вміст робочої теки.

ВИМІРЯНО 02.09.2026, і вимір коштував повного прогону мутацій:

    shutil.Error: [Errno 2] No such file or directory:
        'config/corpus/attachments/__wordy_404__.html'

Файл існував у мить перелічення й зник до копіювання. Створює його
`apps/api/tests/test_doctrine_catalog.py:958` — тест пише ТИМЧАСОВИЙ ФАЙЛ УСЕРЕДИНУ
ДЕРЕВА. Отже будь-яка побічна активність валила мутації цілком, а причина не мала
жодного стосунку до предмета виміру.

Обхід файлової системи був хибний і за ОБСЯГОМ:
    обхід ФС (без .git/.venv/node_modules)  5063 файли
    `git ls-files`                          2595 файлів
2468 зайвих копіювань на КОЖЕН із мутантів із повною копією — кеші, звіти й артефакти
прогонів, яких мутант не читає ніколи.

Це той самий закон, що вже записаний у `provenance._tracked_paths`: обхід файлової
системи не є властивістю коміту. Тут він перевіряється окремо, бо один раз записаний
закон не поширюється сам.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
_SPEC = importlib.util.spec_from_file_location(
    "mutation_runner", ROOT / "scripts/run_mutation_tests.py"
)
assert _SPEC and _SPEC.loader
runner = importlib.util.module_from_spec(_SPEC)
# Реєстрація ДО виконання обов'язкова: `@dataclass` шукає простір імен модуля через
# `sys.modules[cls.__module__]`, і без цього рядка збірка падає з `NoneType` замість
# того, щоб сказати про предмет.
sys.modules[_SPEC.name] = runner
_SPEC.loader.exec_module(runner)


def test_the_sandbox_contains_the_tracked_tree(tmp_path: Path):
    destination = tmp_path / "repo"
    runner.copy_repository(destination)
    tracked = (
        subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True)
        .stdout.decode("utf-8", "surrogateescape")
        .split("\0")
    )
    names = [name for name in tracked if name]
    assert names, "порожній перелік відстеженого — зламаний вимір, не порожнє дерево"
    missing = [name for name in names[:400] if not (destination / name).exists()]
    assert not missing, f"пісочниця не містить відстежених файлів: {missing[:5]}"


def test_the_sandbox_excludes_run_artefacts(tmp_path: Path):
    """Негативний контроль на ОБСЯГ: інакше тест вище був би зелений і на копії всього.

    `var/` ігнорований git'ом і містить бази й звіти прогонів. Якщо він потрапляє в
    пісочницю, копіювання знову стає вдвічі дорожчим і знову крихким.
    """
    destination = tmp_path / "repo"
    runner.copy_repository(destination)
    assert not (destination / "var" / "runtime").exists(), "артефакти прогону в пісочниці"
    assert not (destination / ".git").exists(), ".git у пісочниці"


def test_a_transient_untracked_file_does_not_break_the_copy(tmp_path: Path):
    """Головне: саме цей випадок валив прогін.

    Незатрекований файл, що зникає під час копіювання, більше не існує для пісочниці —
    вона його не перелічує взагалі.
    """
    transient = ROOT / "config/corpus/attachments/__sandbox_scope_probe__.html"
    transient.write_text("проба", encoding="utf-8")
    try:
        destination = tmp_path / "repo"
        runner.copy_repository(destination)
        assert not (destination / "config/corpus/attachments/__sandbox_scope_probe__.html").exists()
    finally:
        transient.unlink(missing_ok=True)


def test_an_undescribed_tree_is_a_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """«Не знаю обсягу» ≠ «обсяг порожній» ≠ «копіюй усе».

    Без цього контролю відмова лишалася б твердженням у коді, якого ніхто не перевіряв.
    """

    class _Failed:
        returncode = 1
        stdout = b""

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: _Failed())
    with pytest.raises(RuntimeError, match="недоступний"):
        runner.copy_repository(tmp_path / "a")

    class _Empty:
        returncode = 0
        stdout = b""

    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: _Empty())
    with pytest.raises(RuntimeError, match="порожній"):
        runner.copy_repository(tmp_path / "b")
