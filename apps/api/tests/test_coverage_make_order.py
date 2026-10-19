"""Exercise Make's scheduler; fixture commands do not stand in for measured coverage."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("producer_fails", [False, True])
def test_parallel_ratchet_waits_for_successful_sqlite_producer(
    tmp_path: Path, producer_fails: bool
) -> None:
    (tmp_path / "Makefile").write_bytes((ROOT / "Makefile").read_bytes())
    (tmp_path / "var").mkdir()
    postgres = tmp_path / "var/coverage-postgres.json"
    postgres.write_text("downloaded-current-run-input")
    command = tmp_path / "fixture-python"
    command.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys, time\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "if 'scripts/collect_dialect_coverage.py' in args:\n"
        "    time.sleep(0.2)\n"
        "    if os.environ['FIXTURE_PRODUCER_FAILS'] == '1': sys.exit(42)\n"
        "    Path('var/sqlite-finished').touch()\n"
        "elif 'scripts/check_coverage_thresholds.py' in args:\n"
        "    assert Path('var/sqlite-finished').is_file()\n"
        "elif 'scripts/merge_dialect_coverage.py' in args:\n"
        "    assert Path('var/sqlite-finished').is_file(), 'merge raced the producer'\n"
        "    assert Path('var/coverage-postgres.json').is_file()\n"
        "    Path('var/union-finished').touch()\n"
        "elif 'scripts/coverage_gap_plan.py' in args:\n"
        "    assert Path('var/union-finished').is_file(), 'ratchet raced the union'\n"
        "else: raise AssertionError(args)\n",
        encoding="utf-8",
    )
    command.chmod(0o755)
    result = subprocess.run(
        ["make", "-j8", "coverage-ratchet", f"PY={command}"],
        cwd=tmp_path,
        env={**os.environ, "FIXTURE_PRODUCER_FAILS": str(int(producer_fails))},
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert (result.returncode == 0) is not producer_fails, result.stdout + result.stderr
    assert (tmp_path / "var/union-finished").is_file() is not producer_fails
    assert postgres.read_text() == "downloaded-current-run-input"
