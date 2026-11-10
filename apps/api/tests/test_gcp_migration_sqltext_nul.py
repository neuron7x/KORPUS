"""Full migration admission must reject nested NUL text defaults."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.gcp.validate_migration_compatibility import evaluate


@pytest.mark.parametrize(
    ("default", "expected"),
    [
        ("'ordinary'", "PASS"),
        ("sa.text(\"'ordinary'\")", "PASS"),
        ("'before\\x00after'", "FAIL"),
        ("sa.text(\"'before\\x00after'\")", "FAIL"),
        ("sa.text(\"'\\x00after'\")", "FAIL"),
        ("sa.text(\"'42'\")", "PASS"),
    ],
)
def test_nested_nul_server_default_fails_closed(
    tmp_path: Path, default: str, expected: str
) -> None:
    versions = tmp_path / "apps/api/migrations/versions"
    versions.mkdir(parents=True)
    baseline = versions / "0000_base.py"
    baseline.write_text('revision = "r0"\ndown_revision = None\ndef upgrade():\n    pass\n')
    policy = tmp_path / "config/production/migration-policy.json"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        json.dumps(
            {
                "baseline_revision": "r0",
                "baseline_files": {
                    "apps/api/migrations/versions/0000_base.py": hashlib.sha256(
                        baseline.read_bytes()
                    ).hexdigest()
                },
                "future_upgrade_forbidden_calls": ["execute", "drop_column", "drop_table"],
            }
        )
    )
    (versions / "0001_future.py").write_text(
        "from alembic import op\nimport sqlalchemy as sa\n"
        'revision = "r1"\ndown_revision = "r0"\n'
        "def upgrade():\n"
        "    op.add_column('accounts', sa.Column('notes', sa.Text(), "
        f"nullable=True, server_default={default}))\n"
    )
    report = evaluate(tmp_path)
    assert report["status"] == expected, report
    if expected == "FAIL":
        assert any("NUL" in finding for finding in report["findings"]), report
