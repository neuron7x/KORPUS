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


def test_false_or_unproven_nullable_without_default_fails_closed(tmp_path: Path) -> None:
    for index, nullable in enumerate(("0", "bool(0)", "not True")):
        root = _copy_surface(tmp_path / f"nullable-poison-{index}")
        _future(
            root,
            f"op.add_column('accounts', sa.Column('nickname', sa.Text(), nullable={nullable}))",
        )
        report = evaluate(root)
        assert report["status"] == "FAIL", (nullable, report)
        assert any("server_default" in reason for reason in report["findings"]), report


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


def test_unsafe_nested_definition_time_effects_fail_closed(tmp_path: Path) -> None:
    poison = (
        "class Hidden:\n    op.drop_table('accounts')",
        "def dormant(default=op.drop_table('accounts')):\n    pass",
        "@identity(op.drop_table('accounts'))\ndef dormant():\n    pass",
        "async def dormant(default=op.execute('DROP TABLE accounts')):\n    pass",
        "func = lambda default=op.execute('DROP TABLE accounts'): default",
    )
    for index, body in enumerate(poison):
        root = _copy_surface(tmp_path / f"definition-time-{index}")
        _future(root, body)
        report = evaluate(root)
        assert report["status"] == "FAIL", (index, report)
        assert any(
            "definition-time" in reason or "class definition" in reason
            for reason in report["findings"]
        ), (index, report)


def test_unsafe_import_time_definition_is_rejected(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    report = _with_helper(
        root, "pass", "def dormant(default=op.drop_table('accounts')):\n    pass\n"
    )
    assert report["status"] == "FAIL", report
    assert any("definition-time" in reason for reason in report["findings"])


def test_safe_literal_defaults_and_annotations_remain_allowed(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    _future(root, "def helper(value=1) -> None:\n    pass\nhelper()")
    report = evaluate(root)
    assert report["status"] == "PASS", report


def test_lambda_callbacks_cannot_hide_unsafe_sql(tmp_path: Path) -> None:
    poison = (
        "sorted([2, 1], key=lambda x: op.execute('DROP TABLE accounts'))",
        "min([1], key=lambda x: op.execute('DROP TABLE accounts'))",
        "max([1], key=lambda x: op.drop_table('accounts'))",
        "sorted([2, 1], key=lambda x: (op.execute('DROP TABLE accounts'), x)[-1])",
    )
    for index, body in enumerate(poison):
        root = _copy_surface(tmp_path / f"callback-poison-{index}")
        _future(root, body)
        report = evaluate(root)
        assert report["status"] == "FAIL", (index, report)
        assert any(
            "lambda has unverified executable callback body" in reason
            for reason in report["findings"]
        ), (index, report)


def test_module_lambda_callbacks_fail_closed(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    report = _with_helper(
        root,
        "sorted([2, 1], key=payload)",
        "payload = lambda x: op.execute('DROP TABLE accounts')",
    )
    assert report["status"] == "FAIL", report
    assert any(
        "lambda has unverified executable callback body" in reason for reason in report["findings"]
    ), report


def test_simple_pure_lambda_callback_remains_admitted(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    _future(root, "sorted([2, 1], key=lambda x: x)")
    report = evaluate(root)
    assert report["status"] == "PASS", report


def test_conditional_or_late_creation_cannot_license_existing_alter(tmp_path: Path) -> None:
    poison = (
        (
            "if False:\n    op.create_table('accounts')\n"
            "op.execute('ALTER TABLE accounts DISABLE ROW LEVEL SECURITY')",
            "",
        ),
        (
            "if 0:\n    op.create_table('accounts')\n"
            "op.execute('ALTER TABLE accounts DISABLE ROW LEVEL SECURITY')",
            "",
        ),
        (
            "make_new()\nop.execute('ALTER TABLE accounts DISABLE ROW LEVEL SECURITY')",
            "def make_new():\n    if False:\n        op.create_table('accounts')\n",
        ),
        (
            "if False:\n    make_new()\n"
            "op.execute('ALTER TABLE accounts DISABLE ROW LEVEL SECURITY')",
            "def make_new():\n    op.create_table('accounts')\n",
        ),
        (
            "op.execute('ALTER TABLE accounts DISABLE ROW LEVEL SECURITY')\n"
            "op.create_table('accounts')",
            "",
        ),
        (
            "make_new()\nop.execute('ALTER TABLE accounts DISABLE ROW LEVEL SECURITY')",
            "def make_new():\n    return\n    op.create_table('accounts')\n",
        ),
    )
    for index, (body, helper) in enumerate(poison):
        root = _copy_surface(tmp_path / f"create-order-{index}")
        result = _with_helper(root, body, helper)
        assert result["status"] == "FAIL", (index, result)
        assert any("ALTER TABLE accounts" in item for item in result["findings"]), result


def test_transitively_ordered_create_remains_admissible(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    result = _with_helper(
        root,
        "make_outer()\nop.execute('ALTER TABLE widgets ENABLE ROW LEVEL SECURITY')",
        "def make_outer():\n    make_inner()\n"
        "def make_inner():\n"
        "    op.create_table('widgets', sa.Column('id', sa.Integer()))\n",
    )
    assert result["status"] == "PASS", result


def test_repeated_alter_helper_requires_prior_creation_each_time(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    result = _with_helper(
        root,
        "alter()\nop.create_table('widgets', sa.Column('id', sa.Integer()))\nalter()",
        "def alter():\n    op.execute('ALTER TABLE widgets ENABLE ROW LEVEL SECURITY')\n",
    )
    assert result["status"] == "FAIL", result
    assert any("ALTER TABLE widgets" in item for item in result["findings"]), result


def test_helper_rebinding_cannot_hide_destructive_sql(tmp_path: Path) -> None:
    poison = (
        ("helper = op.drop_table\nhelper('accounts')", "def helper():\n    pass"),
        (
            "helper = op.execute\nhelper('DROP TABLE accounts')",
            "def helper():\n    pass",
        ),
        (
            "for helper in (op.drop_table,):\n    helper('accounts')",
            "def helper():\n    pass",
        ),
        (
            "[helper('accounts') for helper in [op.drop_table]]",
            "def helper():\n    pass",
        ),
        (
            "from mock_op import drop_table as helper\nhelper('accounts')",
            "def helper():\n    pass",
        ),
        (
            "helper('accounts')",
            "def helper():\n    pass\nfrom mock_op import drop_table as helper",
        ),
        (
            "caller(op.drop_table)",
            "def helper():\n    pass\ndef caller(helper):\n    helper('accounts')",
        ),
    )
    for index, (body, helpers) in enumerate(poison):
        root = _copy_surface(tmp_path / f"helper-rebinding-{index}")
        report = _with_helper(root, body, helpers)
        assert report["status"] == "FAIL", (index, report)
        assert any("ambiguous helper: helper" in item for item in report["findings"]), (
            index,
            report,
        )


def test_unsafe_future_import_bindings_are_rejected(tmp_path: Path) -> None:
    poison = (
        "from fake import drop_table as sorted\nsorted('accounts')",
        "from fake import drop_table as min\nmin('accounts')",
        "from fake import drop_table as max\nmax('accounts')",
        "from fake import op\nop.create_table('widgets')",
        "import fake as sa\nsa.Column('widgets')",
    )
    for index, body in enumerate(poison):
        root = _copy_surface(tmp_path / f"import-shadow-{index}")
        _future(root, body)
        result = evaluate(root)
        assert result["status"] == "FAIL", (index, result)
        assert any("unverified import shadows callable" in item for item in result["findings"]), (
            result
        )


def test_future_wildcard_import_is_rejected(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    result = _with_helper(root, "sorted([1, 2])", "from fake import *")
    assert result["status"] == "FAIL", result
    assert any("unresolved wildcard import" in item for item in result["findings"])


def test_canonical_future_imports_remain_allowed(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    _future(
        root,
        "from alembic import op\nimport sqlalchemy as sa\n"
        "op.create_table('widgets', sa.Column('id', sa.Integer()))",
    )
    result = evaluate(root)
    assert result["status"] == "PASS", result


def test_protected_operation_attribute_rebinding_fails_closed(tmp_path: Path) -> None:
    poison = (
        "op.create_table = op.drop_table\nop.create_table('accounts')",
        "op.create_table: object = op.drop_table\nop.create_table('accounts')",
        "op.create_table += op.drop_table\nop.create_table('accounts')",
        "op.create_table, unused = op.drop_table, None\nop.create_table('accounts')",
        "del op.create_table\nop.create_table('accounts')",
        "op.create_table.__call__ = op.drop_table\nop.create_table('accounts')",
        "sa.Column = op.drop_table\nop.add_column('accounts', sa.Column('id'))",
        "def helper():\n    op.create_table = op.drop_table\nhelper()\nop.create_table('accounts')",
    )
    for index, body in enumerate(poison):
        root = _copy_surface(tmp_path / f"attribute-rebind-{index}")
        _future(root, body)
        report = evaluate(root)
        assert report["status"] == "FAIL", (index, report)
        assert any("trusted callable rebound" in item for item in report["findings"]), (
            index,
            report,
        )


def test_unmodified_alembic_create_and_alter_stay_admitted(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    _future(
        root,
        "op.create_table('widgets', sa.Column('id', sa.Integer()))\n"
        "op.execute('ALTER TABLE widgets ENABLE ROW LEVEL SECURITY')",
    )
    report = evaluate(root)
    assert report["status"] == "PASS", report


def test_trusted_namespace_alias_escape_and_callback_are_denied(tmp_path: Path) -> None:
    creation = (
        "op.create_table('accounts')\nop.execute('ALTER TABLE accounts DISABLE ROW LEVEL SECURITY')"
    )
    poison = (
        ("alias = op\nalias.create_table = op.drop_table\n" + creation, ""),
        ("holder = (op,)\nholder[0].create_table = op.drop_table\n" + creation, ""),
        ("op.__dict__['create_table'] = op.drop_table\n" + creation, ""),
        (
            "sa.__dict__['Column'] = sa.Text\n"
            "op.create_table('accounts', sa.Column('x', sa.Text()))\n"
            "op.execute('ALTER TABLE accounts ENABLE ROW LEVEL SECURITY')",
            "",
        ),
        (
            "rewrite(op)\n" + creation,
            "def rewrite(target):\n    target.create_table = target.drop_table\n",
        ),
        (
            "sorted([1], key=rewrite)\n" + creation,
            "def rewrite(_):\n    op.create_table = op.drop_table\n",
        ),
    )
    for index, (body, helpers) in enumerate(poison):
        root = _copy_surface(tmp_path / f"trusted-escape-{index}")
        report = _with_helper(root, body, helpers)
        assert report["status"] == "FAIL", (index, report)
        assert any(
            "trusted namespace" in finding or "unverified named callback" in finding
            for finding in report["findings"]
        ), (index, report)


def test_trusted_namespace_escape_guard_preserves_valid_calls(tmp_path: Path) -> None:
    accepted = (
        "op.create_table('widgets', sa.Column('id', sa.Integer()))\n"
        "op.execute('ALTER TABLE widgets ENABLE ROW LEVEL SECURITY')",
        "sorted([2, 1], key=lambda x: x)",
    )
    for index, body in enumerate(accepted):
        root = _copy_surface(tmp_path / f"trusted-escape-positive-{index}")
        _future(root, body)
        report = evaluate(root)
        assert report["status"] == "PASS", (index, report)


def test_shadowed_builtin_callback_cannot_imitate_trusted_key(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    report = _with_helper(
        root,
        "sorted([1], key=str)\n"
        "op.create_table('accounts')\n"
        "op.execute('ALTER TABLE accounts DISABLE ROW LEVEL SECURITY')",
        "def str(_):\n    op.create_table = op.drop_table\n",
    )
    assert report["status"] == "FAIL", report
    assert any("unverified named callback" in finding for finding in report["findings"]), report


def test_disconnected_future_migration_cycles_are_rejected(tmp_path: Path) -> None:
    cases = (
        (("0025_cycle_a", "0025_cycle_b"), ("0025_cycle_b", "0025_cycle_a")),
        (("0025_self_cycle", "0025_self_cycle"),),
    )
    for index, edges in enumerate(cases):
        root = _copy_surface(tmp_path / f"cycle-{index}")
        versions = root / "apps/api/migrations/versions"
        for revision, down in edges:
            (versions / f"{revision}.py").write_text(
                "from alembic import op\n"
                f"revision = {revision!r}\n"
                f"down_revision = {down!r}\n"
                "def upgrade():\n    pass\n"
                "def downgrade():\n    pass\n",
                encoding="utf-8",
            )
        report = evaluate(root)
        assert report["status"] == "FAIL", (index, report)
        assert any(
            "disconnected migration revisions" in finding for finding in report["findings"]
        ), (index, report)


def test_ordered_future_migration_extensions_remain_admitted(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    _future(root, "op.create_table('widgets_a', sa.Column('id', sa.Integer()))", revision="0025_a")
    _future(root, "op.create_table('widgets_b', sa.Column('id', sa.Integer()))", revision="0026_b")
    report = evaluate(root)
    assert report["status"] == "PASS", report
    assert report["future_migrations"] == 2


def test_future_revision_metadata_rebinding_is_rejected(tmp_path: Path) -> None:
    poison = (
        "revision = '0025_different'",
        "down_revision = 'missing_parent'",
        "down_revision = 'wrong_' + 'parent'",
        "if True:\n    revision = '0025_conditional'",
        "from unknown_module import revision",
        "def rewrite():\n    global revision\n    revision = '0025_other'\nrewrite()",
        "def rewrite():\n    global down_revision\n    down_revision = 'missing_parent'\nrewrite()",
    )
    for index, trailer in enumerate(poison):
        root = _copy_surface(tmp_path / f"revision-binding-{index}")
        path = _future(root, "op.create_table('widgets', sa.Column('id', sa.Integer()))")
        path.write_text(
            path.read_text(encoding="utf-8") + "\n" + trailer + "\n",
            encoding="utf-8",
        )
        report = evaluate(root)
        assert report["status"] == "FAIL", (index, report)


def test_unused_local_revision_name_preserves_valid_migration(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    result = _with_helper(
        root,
        "op.create_table('widgets', sa.Column('id', sa.Integer()))",
        "def unrelated():\n    revision = 'only_local'\n",
    )
    assert result["status"] == "PASS", result
