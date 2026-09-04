from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _make_value(name: str) -> str:
    recipe = f"__print_runtime_path:\n\t@printf '%s\\n' \"$({name})\""
    completed = subprocess.run(
        [
            "make",
            "--no-print-directory",
            "-s",
            "--eval",
            recipe,
            "__print_runtime_path",
            f"PY={sys.executable}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def test_make_runtime_paths_are_rooted_in_the_canonical_declaration() -> None:
    registry = json.loads(
        (ROOT / "config/operations/canonical-state.json").read_text(encoding="utf-8")
    )
    canonical = Path(registry["canonical_root"])

    assert _make_value("SERVED_CORPUS") == str(
        canonical / "var/runtime/corpus-v6-20260807/korpus.db"
    )
    assert _make_value("SERVED_OBJECTS") == str(
        canonical / "var/runtime/corpus-v6-20260807/objects"
    )
