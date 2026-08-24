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


def _future(root: Path, body: str, *, revision: str = "0018_test") -> Path:
    path = root / f"apps/api/migrations/versions/{revision}.py"
    path.write_text(
        "from alembic import op\nimport sqlalchemy as sa\n"
        f"revision = {revision!r}\n"
        "down_revision = '0017_learning_mastery'\n"
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


def test_raw_sql_future_migration_is_rejected_by_default(tmp_path: Path) -> None:
    root = _copy_surface(tmp_path)
    _future(root, "op.execute('DROP TABLE accounts')")
    report = evaluate(root)
    assert report["status"] == "FAIL"
    assert any("op.execute" in item for item in report["findings"])
