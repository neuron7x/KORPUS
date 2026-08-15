"""The assurance digest must bind the files that choose how assurance executes."""
from __future__ import annotations

from pathlib import Path

from korpus.application.evidence_digest import EVIDENCE_SOURCE_PATHS, compute_source_digest

ORCHESTRATION = {"Makefile", ".github/workflows/assurance.yml"}
PRE_FIX_SOURCES = tuple(path for path in EVIDENCE_SOURCE_PATHS if path not in ORCHESTRATION)


def _seed(tmp_path: Path) -> Path:
    root = tmp_path / "tree"
    (root / "apps/api/src/korpus").mkdir(parents=True)
    (root / ".github/workflows").mkdir(parents=True)
    (root / "apps/api/src/korpus/policy.py").write_text(
        "threshold = 1.0\n",
        encoding="utf-8",
    )
    (root / "Makefile").write_text(
        "mutation:\n\tpython scripts/run_mutation.py\n",
        encoding="utf-8",
    )
    (root / ".github/workflows/assurance.yml").write_text(
        "jobs:\n  assurance:\n    runs-on: ubuntu-24.04\n",
        encoding="utf-8",
    )
    return root


def test_pre_fix_surface_does_not_notice_makefile_orchestration_change(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    old_before = compute_source_digest(root, PRE_FIX_SOURCES)
    current_before = compute_source_digest(root)

    (root / "Makefile").write_text(
        "mutation:\n\tKORPUS_MUTATION_SHARDS=1 python scripts/run_mutation.py\n",
        encoding="utf-8",
    )

    assert compute_source_digest(root, PRE_FIX_SOURCES) == old_before
    assert compute_source_digest(root) != current_before


def test_pre_fix_surface_does_not_notice_assurance_runtime_change(tmp_path: Path) -> None:
    root = _seed(tmp_path)
    old_before = compute_source_digest(root, PRE_FIX_SOURCES)
    current_before = compute_source_digest(root)

    (root / ".github/workflows/assurance.yml").write_text(
        "jobs:\n  assurance:\n    runs-on: ubuntu-22.04\n",
        encoding="utf-8",
    )

    assert compute_source_digest(root, PRE_FIX_SOURCES) == old_before
    assert compute_source_digest(root) != current_before
