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

import pytest

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
    entry["integrity_anchor"] = {
        "path": "config/corpus/mod_snapshots/sukhoputni.txt",
        "sha256": "0" * 64,
    }
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
    entry["integrity_anchor"] = {
        "path": "config/corpus/mod_snapshots/sukhoputni.txt",
        "sha256": "deadbeef",
    }
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


def _attached_entry() -> dict:
    """A source whose page names a DOCX carrying most of its normative content."""
    entry = _probed_entry()
    entry["content_probe"]["required_attachments"] = [
        "https://zakon.rada.gov.ua/laws/file/text/135/f499126n54.docx"
    ]
    entry["attachment_anchors"] = [
        {
            "uri": "https://zakon.rada.gov.ua/laws/file/text/135/f499126n54.docx",
            "path": "config/corpus/attachments/ORG-MOD-ORDER-317__f499126n54.docx",
            "sha256": "0be50eaef9e67c5c68f1fcb91f71b772f457fb834a7e5a82b5f02dcb6e97b1ed",
            "bytes": 98419,
            "captured_on": "2026-08-29",
            "extractor_supports_format": True,
        }
    ]
    return entry


def test_a_captured_attachment_matching_its_digest_passes() -> None:
    assert _validator()._entry_problems(_attached_entry()) == []


def test_a_required_attachment_nobody_captured_is_refused() -> None:
    """Three quarters of order 317 lives in that DOCX; naming it is not fetching it."""
    entry = _attached_entry()
    entry["attachment_anchors"] = []
    problems = _validator()._entry_problems(entry)
    assert any("no attachment anchor captured it" in p for p in problems), problems


def test_a_required_attachment_with_no_anchors_field_at_all_is_refused() -> None:
    entry = _attached_entry()
    entry.pop("attachment_anchors")
    problems = _validator()._entry_problems(entry)
    assert any("attachment_anchors is absent" in p for p in problems), problems


def test_a_tampered_attachment_is_refused() -> None:
    entry = _attached_entry()
    entry["attachment_anchors"][0]["sha256"] = "c" * 64
    problems = _validator()._entry_problems(entry)
    assert any("integrity_anchor mismatch" in p for p in problems), problems


def test_an_attachment_claiming_a_format_the_extractor_cannot_read_is_refused() -> None:
    """The .doc annexes of 548-XIV are captured but unreadable; the catalog must say so."""
    entry = _attached_entry()
    entry["attachment_anchors"][0]["path"] = (
        "config/corpus/attachments/ORG-LAW-548-XIV__f33093n2372.doc"
    )
    entry["attachment_anchors"][0]["sha256"] = _digest_of(
        "config/corpus/attachments/ORG-LAW-548-XIV__f33093n2372.doc"
    )
    problems = _validator()._entry_problems(entry)
    assert any("SUPPORTED_SUFFIXES" in p for p in problems), problems


def test_an_unreadable_attachment_marked_honestly_passes() -> None:
    entry = _attached_entry()
    anchor = entry["attachment_anchors"][0]
    anchor["path"] = "config/corpus/attachments/ORG-LAW-548-XIV__f33093n2372.doc"
    anchor["sha256"] = _digest_of(anchor["path"])
    anchor["extractor_supports_format"] = False
    entry["content_probe"]["required_attachments"] = [anchor["uri"]]
    assert _validator()._entry_problems(entry) == []


def test_an_attachment_anchor_that_is_not_an_object_is_refused() -> None:
    entry = _attached_entry()
    entry["attachment_anchors"] = ["f499126n54.docx"]
    problems = _validator()._entry_problems(entry)
    assert any("not an object" in p for p in problems), problems


def test_every_captured_attachment_in_the_catalog_still_matches_its_digest() -> None:
    catalog = _catalog()
    anchored = [e for e in catalog["sources"] if e.get("attachment_anchors")]
    assert anchored, "the catalog captured no attachments at all"
    result = _validator().evaluate(catalog)
    assert result["status"] == "PASS", result["problems"]
    assert result["summary"]["attachments_captured"] == sum(
        len(e["attachment_anchors"]) for e in anchored
    )


def _digest_of(relative: str) -> str:
    import hashlib

    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def test_a_repealed_act_may_not_be_ingestible() -> None:
    """Rule 12: a dead law still returns 200 and still reads like law."""
    entry = _probed_entry()
    entry["content_probe"]["legal_status"] = "invalid"
    entry["content_probe"]["legal_status_text"] = "втратив чинність"
    problems = _validator()._entry_problems(entry)
    assert any("may not answer a question" in p for p in problems), problems


def test_a_repealed_act_kept_for_reference_but_blocked_is_allowed() -> None:
    entry = _probed_entry()
    entry["content_probe"]["legal_status"] = "invalid"
    entry["ingestible"] = False
    entry["ingest_block_reason"] = "repealed; retained for amendment history only"
    assert _validator()._entry_problems(entry) == []


def test_an_act_in_force_is_not_blocked_by_rule_twelve() -> None:
    entry = _probed_entry()
    entry["content_probe"]["legal_status"] = "valid"
    assert _validator()._entry_problems(entry) == []


def test_a_captured_error_page_under_a_docx_name_is_refused(tmp_path: Path) -> None:
    """The failure a digest check cannot see: curl saved a 404, not the annex."""
    import hashlib

    fake = ROOT / "config/corpus/attachments/__signature_probe__.docx"
    fake.write_bytes(b"<html><body>404 Not Found</body></html>")
    try:
        entry = _attached_entry()
        anchor = entry["attachment_anchors"][0]
        anchor["path"] = "config/corpus/attachments/__signature_probe__.docx"
        anchor["sha256"] = hashlib.sha256(fake.read_bytes()).hexdigest()
        problems = _validator()._entry_problems(entry)
        assert any("does not start with the .docx signature" in p for p in problems), problems
    finally:
        fake.unlink()


def test_every_captured_attachment_carries_the_signature_its_extension_claims() -> None:
    """The live check across all 30 captures, not a fixture."""
    catalog = _catalog()
    result = _validator().evaluate(catalog)
    assert result["status"] == "PASS", result["problems"]
    assert result["summary"]["attachments_captured"] >= 30


def test_the_suffix_set_is_read_from_the_extractor_not_copied() -> None:
    """Rule 11 must agree with what the ingester accepts, and agree without importing it."""
    from korpus.infrastructure.extraction import SUPPORTED_SUFFIXES as imported

    assert _validator()._supported_suffixes() == frozenset(imported)


def test_the_validator_runs_without_the_extractor_s_dependencies(tmp_path: Path) -> None:
    """It has to work inside an unpacked release archive, where no virtualenv exists.

    Importing extraction.py pulls pypdf. A validator that needs a built environment cannot
    check the archive it is shipped in, which is the one place the check matters most.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "import pypdf"], capture_output=True, check=False
    )
    if result.returncode != 0:  # pragma: no cover - only on an interpreter lacking pypdf
        pytest.skip("pypdf is absent; the isolation this test asserts is already the default")

    source = (ROOT / "scripts/validate_doctrine_catalog.py").read_text(encoding="utf-8")
    assert "from korpus.infrastructure.extraction import" not in source, (
        "the validator imports the extractor again; it will fail on a bare interpreter"
    )
