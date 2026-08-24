"""The doctrine catalog's provenance rules hold, and each one catches its own violation.

A validator that only ever sees a passing catalog is a validator nobody has falsified. The
real catalog must pass; then, for every rule, a single field is flipped and the validator
must name that entry — the negative control that proves the rule is load-bearing rather
than decorative. This is the same discipline the mutation catalogue enforces on the code.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _validator():
    spec = importlib.util.spec_from_file_location(
        "validate_doctrine_catalog", ROOT / "scripts/validate_doctrine_catalog.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _catalog() -> dict:
    return json.loads(
        (ROOT / "config/corpus/doctrine_catalog_2026.json").read_text(encoding="utf-8")
    )


def _valid_entry() -> dict:
    """A minimal entry that passes every rule, to be corrupted one field at a time."""
    return {
        "id": "TEST-1",
        "canonical_title": "Test",
        "issuer": "Test issuer",
        "source_kind": "primary_official",
        "authority": "official_ua",
        "classification": "public",
        "access_tier": 0,
        "provenance_status": "verified",
        "rights_status": "open",
        "ingestible": True,
        "source_uri": "https://example.org/doc.pdf",
    }


def test_the_real_catalog_passes() -> None:
    result = _validator().evaluate(_catalog())
    assert result["status"] == "PASS", result["problems"]


def test_the_real_catalog_quarantines_the_restricted_nato_ew_doctrine() -> None:
    """AJP-3.6 is RESTRICTED — it must be present but not ingestible."""
    entry = next(e for e in _catalog()["sources"] if e["id"] == "T2B-AJP-3-6-EW")
    assert entry["ingestible"] is False
    assert entry["classification"] == "restricted"
    assert entry["ingest_block_reason"]


def test_the_baseline_entry_is_actually_clean() -> None:
    module = _validator()
    assert module._entry_problems(_valid_entry()) == []


def test_restricted_material_may_not_be_ingestible() -> None:
    entry = _valid_entry()
    entry["classification"] = "restricted"
    entry["access_tier"] = 3
    problems = _validator()._entry_problems(entry)
    assert any("restricted but ingestible=true" in p for p in problems), problems


def test_non_open_rights_may_not_be_ingestible() -> None:
    entry = _valid_entry()
    entry["rights_status"] = "commercial_restricted"
    problems = _validator()._entry_problems(entry)
    assert any("rights_status" in p and "ingestible=true" in p for p in problems), problems


def test_secondary_analysis_must_be_analytical() -> None:
    entry = _valid_entry()
    entry["source_kind"] = "secondary_analysis"
    entry["authority"] = "official_ua"  # a RUSI paper masquerading as an order
    problems = _validator()._entry_problems(entry)
    assert any("secondary_analysis must be authority=analytical" in p for p in problems), problems


def test_unverified_provenance_must_require_a_second_source() -> None:
    entry = _valid_entry()
    entry["provenance_status"] = "unverified_mirror"
    entry.pop("requires_second_source", None)
    problems = _validator()._entry_problems(entry)
    assert any("requires_second_source is not true" in p for p in problems), problems


def test_a_blocked_entry_must_say_why() -> None:
    entry = _valid_entry()
    entry["ingestible"] = False  # no ingest_block_reason
    problems = _validator()._entry_problems(entry)
    assert any("no ingest_block_reason" in p for p in problems), problems


def test_an_ingestible_entry_must_have_a_source_uri() -> None:
    entry = _valid_entry()
    entry["source_uri"] = ""
    problems = _validator()._entry_problems(entry)
    assert any("no source_uri" in p for p in problems), problems


def test_an_unknown_authority_class_is_refused() -> None:
    entry = _valid_entry()
    entry["authority"] = "supreme_commander"  # not an AuthorityClass
    problems = _validator()._entry_problems(entry)
    assert any("unknown authority" in p for p in problems), problems


def test_a_duplicate_id_is_refused() -> None:
    catalog = _catalog()
    catalog["sources"].append(copy.deepcopy(catalog["sources"][0]))
    result = _validator().evaluate(catalog)
    assert result["status"] == "FAIL"
    assert any("listed twice" in p for p in result["problems"])
