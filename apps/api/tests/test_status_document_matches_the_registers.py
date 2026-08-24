"""The status a commander reads carries the numbers the registers hold. Nothing typed.

TECHNICAL_DEBT_V5.md said "31 EXTERNAL_DEBT" while the register held nine: a hand-typed
count of a machine-tracked set, drifted the moment twenty-two findings moved to mitigated
and nobody re-typed the sentence. A commander deciding authorisation read thirty-one
blockers where there were nine.

CURRENT_STATUS.md is generated from the registers. These tests fail if it drifts, and if
the generator's own counts stop matching the registers — so neither the document nor the
generator can quietly disagree with the source of truth.
"""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _generator():
    spec = importlib.util.spec_from_file_location(
        "generate_status", ROOT / "scripts/generate_status.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_document_is_not_stale() -> None:
    module = _generator()
    current = (ROOT / "docs/operations/CURRENT_STATUS.md").read_text(encoding="utf-8")
    assert current == module.render(), "CURRENT_STATUS.md is stale; run scripts/generate_status.py"


def test_the_external_debt_count_is_the_register_count() -> None:
    debt = json.loads(
        (ROOT / "docs/audit/closure/KORPUS_v5_REMAINING_DEBT.json").read_text(encoding="utf-8")
    )
    counts = Counter(item["v5_status"] for item in debt["items"])
    document = (ROOT / "docs/operations/CURRENT_STATUS.md").read_text(encoding="utf-8")
    assert f"**{counts['EXTERNAL_DEBT']}** зовнішніх боргів" in document
    # And the register's own headline count agrees with the per-item tally — a register
    # whose summary and items disagree is the same drift one level down.
    assert debt["counts"]["EXTERNAL_DEBT"] == counts["EXTERNAL_DEBT"]


def test_the_open_grounds_count_excludes_the_can_go_red_ground() -> None:
    grounds = json.loads(
        (ROOT / "config/operations/admission-grounds.json").read_text(encoding="utf-8")
    )
    blocking = [g for g in grounds["grounds"] if g.get("id") != "2.8"]
    document = (ROOT / "docs/operations/CURRENT_STATUS.md").read_text(encoding="utf-8")
    assert f"**{len(blocking)}** відкритих підстав" in document


def test_the_document_never_claims_production_authorization() -> None:
    document = (ROOT / "docs/operations/CURRENT_STATUS.md").read_text(encoding="utf-8")
    assert "**production_authorized:** `false`" in document
    assert "`true`" not in document


def test_the_v5_snapshot_says_it_is_frozen() -> None:
    """The stale numbers stay as history, but the reader is told not to act on them."""
    v5 = (ROOT / "docs/operations/TECHNICAL_DEBT_V5.md").read_text(encoding="utf-8")
    assert "Заморожений знімок v5" in v5
    assert "CURRENT_STATUS.md" in v5
