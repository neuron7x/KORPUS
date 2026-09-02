"""Дефолт, у який не вірить ніхто, крім нього самого, — сирота.

ВИМІРЯНО 02.09.2026. Три дефолти в дереві вказували на `var/korpus-ml.db`. Файла з
таким іменем немає, а журнал вироків від 30.08.2026 каже, що коли він був, то «лишився
ПОРОЖНІМ (4 КБ), тобто не міряв нічого». Один із трьох — бекап: `make backup-sqlite`
виходив із rc=66, теки `var/backups/sqlite/` не існувало, і бекапу живого корпусу на
276 МБ не робилось ЖОДНОГО РАЗУ, тоді як runbook казав про ті самі команди «executable
as written».

Найважливіше — вада вже стріляла й уже була полагоджена: `scripts/serve_public.sh`
несе коментар «a previous deployment silently selected the empty var/korpus-ml.db
instead». Полагодили КОПІЮ, ЩО ЗЛАМАЛАСЬ, а не константу, і три сестри лишились стояти.

Тести тримають те, чого не тримає жоден інший гейт: правило судить ДЖЕРЕЛО, не диск.
Перевірка існування була написана першою і знята власною отрутою живучості — проба
копіює дерево без `var/`, тож у копії немає жодної бази, і гейт червонів би однаково в
чистому клоні, у CI і в продакшенному образі.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "corpus_paths", ROOT / "scripts/check_corpus_path_declarations.py"
)
assert _SPEC and _SPEC.loader
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)

ORPHAN = "var/" + "runtime/orphan/korpus.db"


def test_an_unbacked_default_is_a_failure():
    verdict = gate.assess({ORPHAN: ["scripts/a.py"]}, {})
    assert verdict["status"] == "FAIL"
    assert "не підтверджений" in verdict["problems"][0]


def test_a_default_cannot_corroborate_itself():
    """Місце, що оголосило дефолт, не є для нього підтвердженням."""
    verdict = gate.assess({ORPHAN: ["scripts/a.py"]}, {ORPHAN: ["scripts/a.py"]})
    assert verdict["status"] == "FAIL"


def test_a_config_backs_the_default():
    verdict = gate.assess({ORPHAN: ["scripts/a.py"]}, {ORPHAN: ["config/operations/x.json"]})
    assert verdict["status"] == "PASS"
    assert verdict["problems"] == []


def test_no_defaults_at_all_is_unknown_not_pass():
    """Порожній перелік — зламаний пошук, а не чисте дерево. `all([])` істинне."""
    assert gate.assess({}, {})["status"] == "UNKNOWN"


def test_only_argparse_defaults_count_as_declarations():
    """Звичайна константа і докстрінг дефолтом не є: там шлях подають свідомо."""
    sample = "var/" + "runtime/a/korpus.db"
    assert gate._from_python(f'p(default="{sample}")') == {sample}
    assert gate._from_python(f'DB = "{sample}"') == set()
    assert gate._from_python(f'"""див. {sample}"""') == set()
    # Розрізнення, без якого перевірка проходить і на «будь-який іменований аргумент»:
    # шлях у `help=` описує дефолт, а не задає його.
    assert gate._from_python(f'p("--db", help="раніше було {sample}")') == set()
    assert gate._from_python(f'p("--db", metavar="{sample}")') == set()


def test_shell_reads_the_default_expansion_but_not_a_comment():
    sample = "var/" + "runtime/a/korpus.db"
    assert gate._from_shell('x="${V:-' + sample + '}"') == {sample}
    assert gate._from_shell(f"# старий {sample}") == set()


def test_the_tree_itself_has_no_orphan_default():
    """Негативний контроль на живому дереві: гейт мусить бути зелений ТУТ і зараз."""
    verdict = gate.assess(gate.observe(ROOT), gate._corroborations(ROOT))
    assert verdict["status"] == "PASS", verdict["problems"]
