from __future__ import annotations

import shutil
from pathlib import Path

from scripts.gcp.validate_migration_compatibility import evaluate

ROOT = Path(__file__).resolve().parents[3]


def _copy_surface(tmp_path: Path) -> Path:
    shutil.copytree(
        ROOT / "apps/api/migrations/versions", tmp_path / "apps/api/migrations/versions"
    )
    policy = tmp_path / "config/production/migration-policy.json"
    policy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "config/production/migration-policy.json", policy)
    return tmp_path


def test_current_migration_history_is_compatible() -> None:
    report = evaluate(ROOT)
    assert report["status"] == "PASS", report
    assert report["future_migrations"] == 0


def test_mutated_baseline_history_is_rejected(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    path = root / "apps/api/migrations/versions/0016_learning_course_graph.py"
    path.write_text(path.read_text(encoding="utf-8") + "\n# mutation\n", encoding="utf-8")
    assert evaluate(root)["status"] == "FAIL"


def _current_head(root: Path) -> str:
    """Голова ЦЬОГО дерева, не вписана константа.

    Тут стояло `down_revision = '0018_operational_competencies'`. Синтетична майбутня
    міграція чіплялась за коліно, яке було головою, коли тест писали, — і щойно ланцюг
    подовжили, вона створювала ДРУГУ голову, а тест звинувачував у цьому дерево.
    Перевірка мусить будувати правильний вхід, а не той, що був правильним колись.
    """
    versions = root / "apps/api/migrations/versions"
    revisions: dict[str, str] = {}
    parents: set[str] = set()
    for item in sorted(versions.glob("*.py")):
        text = item.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            for name in ("revision", "down_revision"):
                if stripped.startswith((f"{name} =", f"{name}:")) and "=" in stripped:
                    value = stripped.split("=", 1)[1].strip().strip("\"'")
                    if value in {"None", ""}:
                        continue
                    if name == "revision":
                        revisions[value] = item.name
                    else:
                        parents.add(value)
    heads = [key for key in revisions if key not in parents]
    assert len(heads) == 1, heads
    return heads[0]


def _future(root: Path, body: str, *, revision: str = "0019_test") -> Path:
    path = root / f"apps/api/migrations/versions/{revision}.py"
    path.write_text(
        "from alembic import op\nimport sqlalchemy as sa\n"
        f"revision = {revision!r}\n"
        f"down_revision = {_current_head(root)!r}\n"
        "def upgrade():\n"
        + "\n".join(f"    {line}" for line in body.splitlines())
        + "\ndef downgrade():\n    pass\n",
        encoding="utf-8",
    )
    return path


def test_additive_future_migration_is_allowed(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    _future(root, "op.add_column('accounts', sa.Column('nickname', sa.Text(), nullable=True))")
    report = evaluate(root)
    assert report["status"] == "PASS", report
    assert report["future_migrations"] == 1


def test_destructive_future_migration_is_rejected(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    _future(root, "op.drop_column('accounts', 'nickname')")
    report = evaluate(root)
    assert report["status"] == "FAIL"
    assert any("op.drop_column" in item for item in report["findings"])


def test_non_null_add_without_server_default_is_rejected(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    _future(root, "op.add_column('accounts', sa.Column('nickname', sa.Text(), nullable=False))")
    report = evaluate(root)
    assert report["status"] == "FAIL"
    assert any("server_default" in item for item in report["findings"])


def test_alter_on_a_table_this_migration_creates_is_allowed(tmp_path: Path) -> None:
    """Ревізія N-1 не знає про таблицю, народжену в цьому ж `upgrade()`.

    `ALTER TABLE … ENABLE ROW LEVEL SECURITY` над НАЯВНОЮ таблицею звужує те, що бачить
    стара ревізія застосунку — саме через це 0020 визнали нерозширювальним. Над щойно
    створеною таблицею воно не може зачепити нікого: старий код до неї не звертається.
    Заборона на дієслово не розрізняла цих випадків.
    """
    root = _copy_surface(tmp_path)
    _future(
        root,
        "op.create_table('widgets', sa.Column('id', sa.String(), primary_key=True))\n"
        "op.execute('ALTER TABLE widgets ENABLE ROW LEVEL SECURITY')",
    )
    report = evaluate(root)
    assert report["status"] == "PASS", report


def test_alter_on_a_table_this_migration_does_not_create_is_rejected(tmp_path: Path) -> None:
    """Негативний контроль до дозволу вище: без нього він пропускав би будь-який ALTER."""
    root = _copy_surface(tmp_path)
    _future(root, "op.execute('ALTER TABLE accounts ENABLE ROW LEVEL SECURITY')")
    report = evaluate(root)
    assert report["status"] == "FAIL"
    assert any("accounts" in item for item in report["findings"]), report["findings"]


def test_alter_whose_table_name_is_not_literal_is_rejected(tmp_path: Path) -> None:
    """Невідоме ім'я не дає дозволу: інакше f-рядок обходив би перевірку."""
    root = _copy_surface(tmp_path)
    _future(
        root,
        "op.create_table('widgets', sa.Column('id', sa.String(), primary_key=True))\n"
        "table = 'accounts'\n"
        "op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')",
    )
    report = evaluate(root)
    assert report["status"] == "FAIL", report


def test_raw_sql_future_migration_is_rejected_by_default(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    _future(root, "op.execute('DROP TABLE accounts')")
    report = evaluate(root)
    assert report["status"] == "FAIL"
    assert any("op.execute" in item for item in report["findings"])


def _with_helper(root: Path, upgrade_body: str, helper_source: str) -> dict[str, object]:
    path = _future(root, upgrade_body)
    path.write_text(path.read_text(encoding="utf-8") + "\n" + helper_source, encoding="utf-8")
    return evaluate(root)


def test_direct_helper_cannot_hide_destructive_sql(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    result = _with_helper(
        root, "danger()", "def danger():\n    op.execute('DROP TABLE accounts')\n"
    )
    assert result["status"] == "FAIL"
    assert any("op.execute" in reason for reason in result["findings"])


def test_transitive_helper_cannot_hide_destructive_alembic_call(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    result = _with_helper(
        root,
        "entry()",
        "def entry():\n    leaf()\ndef leaf():\n    op.drop_table('accounts')\n",
    )
    assert result["status"] == "FAIL"
    assert any("op.drop_table" in reason for reason in result["findings"])


def test_local_nested_helper_is_included_when_invoked(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    _future(root, "def erase():\n    op.execute('DROP TABLE accounts')\nerase()")
    result = evaluate(root)
    assert result["status"] == "FAIL"
    assert any("op.execute" in reason for reason in result["findings"])


def test_unused_helper_does_not_create_a_false_positive(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    result = _with_helper(
        root,
        "op.add_column('accounts', sa.Column('label', sa.Text(), nullable=True))",
        "def dormant():\n    op.execute('DROP TABLE accounts')\n",
    )
    assert result["status"] == "PASS", result


def test_created_table_from_reachable_helper_allows_safe_alter(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    result = _with_helper(
        root,
        "create_new()\nop.execute('ALTER TABLE widgets ENABLE ROW LEVEL SECURITY')",
        "def create_new():\n"
        "    op.create_table('widgets', sa.Column('id', sa.String(), primary_key=True))\n",
    )
    assert result["status"] == "PASS", result


def test_unknown_helper_dispatch_fails_closed(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    _future(root, "maybe_run_sql()")
    result = evaluate(root)
    assert result["status"] == "FAIL"
    assert any("unresolved callable" in reason for reason in result["findings"])


def test_dynamic_or_chained_execution_fails_closed(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    _future(root, "op.get_bind().execute('DROP TABLE accounts')")
    result = evaluate(root)
    assert result["status"] == "FAIL"
    assert any("dynamic call target" in reason for reason in result["findings"])


def test_rebinding_safe_builtin_cannot_hide_dynamic_sql(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    _future(root, "str = op.execute\nstr('DROP TABLE accounts')")
    result = evaluate(root)
    assert result["status"] == "FAIL"
    assert any("trusted callable rebound" in reason for reason in result["findings"])

def test_raw_sql_unproven_create_dynamic_and_stacked_are_rejected(tmp_path: Path) -> None:
    poison = (
        "op.execute('CREATE OR REPLACE VIEW v AS SELECT 1')",
        "op.execute('CREATE TRIGGER tr ON accounts')",
        "op.execute('CREATE UNIQUE INDEX ux ON accounts(email)')",
        "op.execute('CREATE TABLE widgets(id bigint); DROP TABLE accounts')",
        "op.execute('CREATE TABLE widgets(id bigint) -- unsafe')",
        "op.execute('CREATE TABLE widgets(id bigint) /* unsafe */')",
        "op.execute(f'CREATE TABLE widgets(id bigint){tail}')",
        "op.execute(sql)",
    )
    for index, snippet in enumerate(poison):
        root = _copy_surface(tmp_path / f"sql-poison-{index}")
        _future(root, snippet)
        report = evaluate(root)
        assert report["status"] == "FAIL", (index, report)


def test_raw_sql_literal_create_table_remains_admissible(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    _future(root, "op.execute('CREATE TABLE widgets(id bigint)')")
    report = evaluate(root)
    assert report["status"] == "PASS", report
