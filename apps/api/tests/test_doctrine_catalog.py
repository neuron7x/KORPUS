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


def test_every_anchored_snapshot_in_the_catalog_still_matches_its_digest() -> None:
    """The live check, not a fixture: an edited or re-fetched snapshot fails here."""
    catalog = _catalog()
    anchored = [e for e in catalog["sources"] if e.get("integrity_anchor")]
    assert anchored, "the catalog records no integrity anchors at all"
    result = _validator().evaluate(catalog)
    assert result["status"] == "PASS", result["problems"]
    assert result["summary"]["integrity_anchored"] == len(anchored)


def test_a_changed_page_snapshot_is_caught() -> None:
    entry = _valid_entry()
    entry["integrity_anchor"] = {"path": "config/corpus/mod_snapshots/sukhoputni.txt", "sha256": "0" * 64}
    problems = _validator()._entry_problems(entry)
    assert any("integrity_anchor mismatch" in p for p in problems), problems


def test_an_anchor_outside_the_repository_is_refused() -> None:
    """An anchor CI cannot read is not an anchor — the reason rule 9 exists."""
    entry = _valid_entry()
    entry["integrity_anchor"] = {"path": "../../../etc/hostname", "sha256": "a" * 64}
    problems = _validator()._entry_problems(entry)
    assert any("escapes the repository" in p for p in problems), problems


def test_a_missing_snapshot_file_is_refused() -> None:
    entry = _valid_entry()
    entry["integrity_anchor"] = {"path": "config/corpus/does-not-exist.txt", "sha256": "b" * 64}
    problems = _validator()._entry_problems(entry)
    assert any("is not a file in the tree" in p for p in problems), problems


def test_an_anchor_that_is_not_an_object_is_refused() -> None:
    entry = _valid_entry()
    entry["integrity_anchor"] = "963c86a3"
    problems = _validator()._entry_problems(entry)
    assert any("not an object" in p for p in problems), problems


def test_an_anchor_digest_that_is_not_a_sha256_is_refused() -> None:
    entry = _valid_entry()
    entry["integrity_anchor"] = {"path": "config/corpus/mod_snapshots/sukhoputni.txt", "sha256": "deadbeef"}
    problems = _validator()._entry_problems(entry)
    assert any("not a sha256 digest" in p for p in problems), problems


def test_an_entry_without_an_anchor_is_still_valid() -> None:
    """Rule 9 constrains anchors; it does not require one of every source."""
    entry = _valid_entry()
    entry.pop("integrity_anchor", None)
    assert _validator()._entry_problems(entry) == []


def _probed_entry() -> dict:
    """A card/print pair as probe_source_content.py records it, print carrying the text."""
    entry = _valid_entry()
    entry["source_uri"] = "https://zakon.rada.gov.ua/laws/show/548-14/print"
    entry["content_probe"] = {
        "probed_on": "2026-08-29",
        "variants": {
            "card": {"uri": "https://zakon.rada.gov.ua/laws/show/548-14", "words": 725},
            "print": {"uri": "https://zakon.rada.gov.ua/laws/show/548-14/print", "words": 66069},
        },
        "chosen_variant": "print",
        "chosen_uri": "https://zakon.rada.gov.ua/laws/show/548-14/print",
        "chosen_words": 66069,
    }
    return entry


def test_a_probed_entry_pointing_at_its_richest_variant_passes() -> None:
    assert _validator()._entry_problems(_probed_entry()) == []


def test_pointing_at_the_card_after_the_probe_found_the_text_elsewhere_is_refused() -> None:
    """The failure mode rule 10 exists for: 200 OK, clean parse, almost no content."""
    entry = _probed_entry()
    entry["source_uri"] = "https://zakon.rada.gov.ua/laws/show/548-14"
    problems = _validator()._entry_problems(entry)
    assert any("almost no text" in p for p in problems), problems


def test_choosing_the_thinner_variant_is_refused() -> None:
    entry = _probed_entry()
    entry["source_uri"] = "https://zakon.rada.gov.ua/laws/show/548-14"
    entry["content_probe"]["chosen_variant"] = "card"
    entry["content_probe"]["chosen_uri"] = "https://zakon.rada.gov.ua/laws/show/548-14"
    entry["content_probe"]["chosen_words"] = 725
    problems = _validator()._entry_problems(entry)
    assert any("points at the thinner variant" in p for p in problems), problems


def test_a_word_count_that_contradicts_its_own_measurement_is_refused() -> None:
    entry = _probed_entry()
    entry["content_probe"]["chosen_words"] = 999999
    problems = _validator()._entry_problems(entry)
    assert any("contradicts the" in p for p in problems), problems


def test_a_chosen_variant_that_was_never_measured_is_refused() -> None:
    entry = _probed_entry()
    entry["content_probe"]["chosen_variant"] = "pdf"
    problems = _validator()._entry_problems(entry)
    assert any("never measured" in p for p in problems), problems


def test_a_probe_with_no_variants_is_refused() -> None:
    entry = _probed_entry()
    entry["content_probe"]["variants"] = {}
    problems = _validator()._entry_problems(entry)
    assert any("records no variants" in p for p in problems), problems


def test_a_variant_without_a_word_count_is_refused() -> None:
    entry = _probed_entry()
    entry["content_probe"]["variants"]["print"] = {"uri": "x"}
    problems = _validator()._entry_problems(entry)
    assert any("no word count" in p for p in problems), problems


def test_a_probe_that_is_not_an_object_is_refused() -> None:
    entry = _probed_entry()
    entry["content_probe"] = "66069 words"
    problems = _validator()._entry_problems(entry)
    assert any("content_probe is not an object" in p for p in problems), problems


def test_an_entry_without_a_probe_is_still_valid() -> None:
    entry = _valid_entry()
    entry.pop("content_probe", None)
    assert _validator()._entry_problems(entry) == []


def test_every_probed_source_in_the_catalog_points_at_its_measured_content() -> None:
    catalog = _catalog()
    probed = [e for e in catalog["sources"] if e.get("content_probe")]
    assert probed, "the catalog records no content probes at all"
    result = _validator().evaluate(catalog)
    assert result["status"] == "PASS", result["problems"]
    assert result["summary"]["content_probed"] == len(probed)
