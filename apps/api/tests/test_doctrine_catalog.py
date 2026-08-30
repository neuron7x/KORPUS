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
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
# Файл вантажить `scripts/validate_doctrine_catalog.py` напряму, а той імпортує сусідів
# (`iso_dates`, `catalog_merge`). Раніше шлях додавав ОДИН тест, тож порядок вирішував,
# чи пройде решта: файл окремо падав трьома ModuleNotFoundError, а в повному прогоні — ні.
# Порядок тестів не сміє бути частиною умови проходження.
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def _validator():
    spec = importlib.util.spec_from_file_location(
        "validate_doctrine_catalog", ROOT / "scripts/validate_doctrine_catalog.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _today() -> str:
    """Probes age out (rule 14 freshness), so a fixture with a fixed date rots."""
    return date.today().isoformat()


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
        "probed_on": _today(),
        "variants": {
            "card": {"uri": "https://zakon.rada.gov.ua/laws/show/548-14", "words": 725},
            "print": {"uri": "https://zakon.rada.gov.ua/laws/show/548-14/print", "words": 66069},
        },
        "chosen_variant": "print",
        "chosen_uri": "https://zakon.rada.gov.ua/laws/show/548-14/print",
        "chosen_words": 66069,
        # Rule 12 reads the portal's marker; an absent one is not "not invalid".
        "legal_status": "valid",
        "legal_status_text": "чинний",
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


def test_marking_an_attachment_unreadable_is_not_enough_on_its_own() -> None:
    """Honest about the format, silent about the content — rule 13 closes that gap.

    Until 2026-08-29 this entry passed: the catalog said "the extractor cannot read this"
    and stopped, which is accurate and tells nobody what the file holds.
    """
    entry = _attached_entry()
    anchor = entry["attachment_anchors"][0]
    anchor["path"] = "config/corpus/attachments/ORG-LAW-548-XIV__f33093n2372.doc"
    anchor["sha256"] = _digest_of(anchor["path"])
    anchor["extractor_supports_format"] = False
    entry["content_probe"]["required_attachments"] = [anchor["uri"]]
    problems = _validator()._entry_problems(entry)
    assert any("nobody has surveyed" in p for p in problems), problems


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


def _unreadable_entry() -> dict:
    """A capture in a format the extractor refuses — 14 of the catalog's 30 are these."""
    entry = _attached_entry()
    anchor = entry["attachment_anchors"][0]
    anchor["path"] = "config/corpus/attachments/ORG-LAW-548-XIV__f33093n2372.doc"
    anchor["sha256"] = _digest_of(anchor["path"])
    anchor["extractor_supports_format"] = False
    anchor["unreadable_content_survey"] = {
        "words": 93,
        "opening": "Зразок Діє в межах ______ (найменування військової частини)",
        "surveyed_with": "LibreOffice 24.2",
        "surveyed_on": _today(),
    }
    entry["content_probe"]["required_attachments"] = [anchor["uri"]]
    return entry


def test_a_surveyed_unreadable_attachment_passes() -> None:
    assert _validator()._entry_problems(_unreadable_entry()) == []


def test_an_unreadable_attachment_with_no_survey_is_refused() -> None:
    """Rule 13: outside the corpus is acceptable; outside anyone's knowledge is not."""
    entry = _unreadable_entry()
    entry["attachment_anchors"][0].pop("unreadable_content_survey")
    problems = _validator()._entry_problems(entry)
    assert any("nobody has surveyed" in p for p in problems), problems


def test_a_survey_that_names_no_tool_is_refused() -> None:
    entry = _unreadable_entry()
    entry["attachment_anchors"][0]["unreadable_content_survey"]["surveyed_with"] = ""
    problems = _validator()._entry_problems(entry)
    assert any("claim without a method" in p for p in problems), problems


def test_a_survey_with_no_word_count_is_refused() -> None:
    entry = _unreadable_entry()
    entry["attachment_anchors"][0]["unreadable_content_survey"]["words"] = 3
    problems = _validator()._entry_problems(entry)
    assert any("below the floor of" in p for p in problems), problems


def test_a_survey_with_no_opening_text_is_refused() -> None:
    entry = _unreadable_entry()
    entry["attachment_anchors"][0]["unreadable_content_survey"]["opening"] = "  .  "
    problems = _validator()._entry_problems(entry)
    assert any("has to identify the document" in p for p in problems), problems


def test_a_survey_that_is_not_an_object_is_refused() -> None:
    entry = _unreadable_entry()
    entry["attachment_anchors"][0]["unreadable_content_survey"] = "93 words"
    problems = _validator()._entry_problems(entry)
    assert any("survey is not an object" in p for p in problems), problems


def test_a_readable_attachment_needs_no_survey() -> None:
    """Rule 13 constrains what cannot be read; it does not tax what can."""
    assert _validator()._entry_problems(_attached_entry()) == []


def test_every_unreadable_capture_in_the_catalog_is_surveyed() -> None:
    catalog = _catalog()
    result = _validator().evaluate(catalog)
    assert result["status"] == "PASS", result["problems"]
    summary = result["summary"]
    assert summary["attachments_surveyed"] == (
        summary["attachments_captured"] - summary["attachments_extractor_readable"]
    )


# --- rule 14 and the type strictness an adversarial pass on 2026-08-29 required -----------
# Each of these reproduces a way the gate returned PASS while measuring nothing.


def test_deleting_the_evidence_is_refused_by_the_floor() -> None:
    """The finding that made rule 14 necessary: 18 of 19 probes and 11 of 12 anchors gone,
    gate PASS, every test green. Each rule measured the quality of evidence that existed and
    none required any to."""
    catalog = _catalog()
    dropped_probe = dropped_anchor = 0
    for entry in catalog["sources"]:
        if entry.get("content_probe") and dropped_probe < 18:
            entry.pop("content_probe")
            dropped_probe += 1
        if entry.get("integrity_anchor") and dropped_anchor < 11:
            entry.pop("integrity_anchor")
            dropped_anchor += 1
    assert (dropped_probe, dropped_anchor) == (18, 11)
    result = _validator().evaluate(catalog)
    assert result["status"] == "FAIL"
    assert any("below the recorded floor" in p for p in result["problems"])


def test_a_catalog_with_no_declared_floor_is_refused() -> None:
    catalog = _catalog()
    catalog.pop("evidence_floor")
    result = _validator().evaluate(catalog)
    assert result["status"] == "FAIL"
    assert any("declares no evidence_floor" in p for p in result["problems"])


def test_a_probeable_source_without_a_probe_is_refused() -> None:
    entry = _probed_entry()
    entry.pop("content_probe")
    problems = _validator()._mandatory_evidence_problems(entry)
    assert any("carries no content_probe" in p for p in problems), problems


def test_an_undated_ministry_page_without_an_anchor_is_refused() -> None:
    entry = _valid_entry()
    entry["source_uri"] = "https://mod.gov.ua/pro-nas/suhoputni-vijska"
    problems = _validator()._mandatory_evidence_problems(entry)
    assert any("carries no integrity_anchor" in p for p in problems), problems


def test_dropping_the_richer_variant_no_longer_hides_the_thinner_one() -> None:
    """Rule 10 compared only declared variants, so deleting `print` made
    'points at the thinner variant' unreachable — the exact substitution it guards."""
    entry = _probed_entry()
    entry["source_uri"] = "https://zakon.rada.gov.ua/laws/show/548-14"
    probe = entry["content_probe"]
    probe["variants"].pop("print")
    probe["chosen_variant"] = "card"
    probe["chosen_uri"] = "https://zakon.rada.gov.ua/laws/show/548-14"
    probe["chosen_words"] = 725
    problems = _validator()._entry_problems(entry)
    assert any("declares no print variant" in p for p in problems), problems


def test_a_float_word_count_is_refused() -> None:
    """66069.0 == 66069 is True, so the contradiction check passed on a number nobody read."""
    entry = _probed_entry()
    entry["content_probe"]["chosen_words"] = 66069.0
    problems = _validator()._entry_problems(entry)
    assert any("is not an integer" in p for p in problems), problems


def test_a_boolean_word_count_is_refused() -> None:
    entry = _probed_entry()
    entry["content_probe"]["variants"]["print"]["words"] = True
    problems = _validator()._entry_problems(entry)
    assert any("has no word count" in p for p in problems), problems


def test_a_stale_probe_is_refused() -> None:
    """An act repealed tomorrow keeps legal_status: valid forever if nothing ages it out."""
    entry = _probed_entry()
    entry["content_probe"]["probed_on"] = "1999-01-01"
    problems = _validator()._entry_problems(entry)
    assert any("days old" in p for p in problems), problems


def test_a_probe_dated_in_the_future_is_refused() -> None:
    entry = _probed_entry()
    entry["content_probe"]["probed_on"] = (date.today() + timedelta(days=2)).isoformat()
    problems = _validator()._entry_problems(entry)
    assert any("in the future" in p for p in problems), problems


@pytest.mark.parametrize("status", ["INVALID", "втратив чинність", "", None])
def test_an_unrecognised_legal_status_is_refused(status: object) -> None:
    """Four separate ways past rule 12: it compared for equality with 'invalid'."""
    entry = _probed_entry()
    if status is None:
        entry["content_probe"].pop("legal_status")
    else:
        entry["content_probe"]["legal_status"] = status
    problems = _validator()._entry_problems(entry)
    assert any("not one of" in p for p in problems), problems


def test_a_status_that_contradicts_its_own_text_is_refused() -> None:
    entry = _probed_entry()
    entry["content_probe"]["legal_status_text"] = "втратив чинність"
    problems = _validator()._entry_problems(entry)
    assert any("disagree" in p for p in problems), problems


def test_an_unreadable_status_may_not_be_ingestible() -> None:
    entry = _probed_entry()
    entry["content_probe"]["legal_status"] = "unknown"
    problems = _validator()._entry_problems(entry)
    assert any("nobody established" in p for p in problems), problems


def test_a_string_ingestible_flag_is_refused() -> None:
    """bool("false") is True: the source counted as ingestible and skipped rule 5."""
    entry = _valid_entry()
    entry["ingestible"] = "false"
    problems = _validator()._entry_problems(entry)
    assert any("must be a boolean" in p for p in problems), problems


def test_a_string_second_source_flag_is_refused() -> None:
    entry = _valid_entry()
    entry["provenance_status"] = "unverified_mirror"
    entry["requires_second_source"] = "no"
    problems = _validator()._entry_problems(entry)
    assert any("must be a boolean" in p for p in problems), problems


def test_an_anchor_on_an_arbitrary_repository_file_is_refused() -> None:
    """Inside the repository was the whole test; an anchor on this validator's own source
    passed, proving a digest rather than that anything was captured."""
    entry = _valid_entry()
    entry["integrity_anchor"] = {
        "path": "scripts/validate_doctrine_catalog.py",
        "sha256": _digest_of("scripts/validate_doctrine_catalog.py"),
    }
    problems = _validator()._entry_problems(entry)
    assert any("is not under" in p for p in problems), problems


def test_a_jar_renamed_docx_is_refused(tmp_path: Path) -> None:
    """Every ZIP starts with PK\\x03\\x04, so the signature alone admitted a .jar."""
    import zipfile

    fake = ROOT / "config/corpus/attachments/__jar_probe__.docx"
    with zipfile.ZipFile(fake, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
        archive.writestr("Evil.class", "\xca\xfe\xba\xbe")
    try:
        entry = _attached_entry()
        anchor = entry["attachment_anchors"][0]
        anchor["path"] = "config/corpus/attachments/__jar_probe__.docx"
        anchor["sha256"] = _digest_of(anchor["path"])
        problems = _validator()._entry_problems(entry)
        assert any("ZIP without word/document.xml" in p for p in problems), problems
    finally:
        fake.unlink()


def test_a_tiny_html_capture_is_refused() -> None:
    """.html has no signature to check, so a saved 404 page passed as an annex."""
    fake = ROOT / "config/corpus/attachments/__tiny_probe__.html"
    fake.write_text("<html>404</html>", encoding="utf-8")
    try:
        entry = _attached_entry()
        anchor = entry["attachment_anchors"][0]
        anchor["path"] = "config/corpus/attachments/__tiny_probe__.html"
        anchor["sha256"] = _digest_of(anchor["path"])
        anchor["extractor_supports_format"] = True
        problems = _validator()._entry_problems(entry)
        assert any("not an annex" in p for p in problems), problems
    finally:
        fake.unlink()


def test_required_attachments_as_a_string_no_longer_disables_the_rule() -> None:
    entry = _attached_entry()
    entry["content_probe"]["required_attachments"] = "https://example.org/a.docx"
    entry.pop("attachment_anchors")
    problems = _validator()._entry_problems(entry)
    assert problems, "a mistyped required_attachments silently switched rule 11 off"


def test_a_placeholder_survey_is_refused() -> None:
    """words: 1, opening: "." satisfied "positive" and "non-empty" and described nothing."""
    entry = _unreadable_entry()
    entry["attachment_anchors"][0]["unreadable_content_survey"].update(
        {"words": 1, "opening": ".", "surveyed_with": "."}
    )
    problems = _validator()._entry_problems(entry)
    assert len([p for p in problems if "unreadable_content_survey" in p]) >= 3, problems


def test_the_ceiling_refuses_one_more_unmeasured_source() -> None:
    """The floor is a scalar: it counts evidence that exists, never notices a source with
    none. 128 of 168 sources hold no probe, no anchor and no capture — their hosts are in
    neither list, so rule 14 asks them for nothing and the floor never drops."""
    catalog = _catalog()
    donor = next(
        entry
        for entry in catalog["sources"]
        if entry.get("ingestible") and not entry.get("content_probe")
    )
    unmeasured = copy.deepcopy(donor)
    unmeasured["id"] = "TEST-UNMEASURED"
    for key in ("content_probe", "integrity_anchor", "attachment_anchors"):
        unmeasured.pop(key, None)
    catalog["sources"].append(unmeasured)

    result = _validator().evaluate(catalog)
    assert result["status"] == "FAIL"
    assert any("above the recorded ceiling" in p for p in result["problems"])


def test_a_catalog_with_no_declared_ceiling_is_refused() -> None:
    catalog = _catalog()
    catalog.pop("evidence_ceiling")
    result = _validator().evaluate(catalog)
    assert result["status"] == "FAIL"
    assert any("declares no evidence_ceiling" in p for p in result["problems"])


def test_deleting_half_the_catalog_is_refused() -> None:
    """At a floor computed for 84 sources, exactly half of a 168-source catalog could be
    deleted with the gate still green — 9 content probes and 52 captured attachments gone."""
    catalog = _catalog()
    keep = len(catalog["sources"]) // 2
    catalog["sources"] = catalog["sources"][:keep]
    result = _validator().evaluate(catalog)
    assert result["status"] == "FAIL"
    assert any("below the recorded floor" in p for p in result["problems"])


@pytest.mark.parametrize(
    ("uri", "matches"),
    [
        ("https://zakon.rada.gov.ua/laws/show/548-14", True),
        # The one that mattered: rule 14 was bypassed by changing the case of the URL.
        ("https://ZAKON.RADA.GOV.UA/laws/show/548-14", True),
        ("https://zakon.rada.gov.ua:443/laws/show/548-14", True),
        # A valid absolute FQDN. DNS resolves it to the same 193.19.153.66, and rule 14
        # did not fire on it — found by an independent session, eighth of the seven probes.
        ("https://zakon.rada.gov.ua./laws/show/548-14", True),
        # userinfo must not be mistaken for the host.
        ("https://zakon.rada.gov.ua@evil.com/x", False),
        ("https://www.zakon.rada.gov.ua/laws/show/548-14", True),
        ("https://zakon.rada.gov.ua.evil.com/laws", False),
        ("https://evil.com/?u=zakon.rada.gov.ua", False),
        ("https://evil.com/zakon.rada.gov.ua/laws", False),
        ("https://mod.gov.ua/pro-nas", False),
    ],
)
def test_host_matching_reads_the_host_not_the_string(uri: str, matches: bool) -> None:
    """`any(h in uri for h in hosts)` was wrong in four of seven cases. Three were false
    positives that cost an unnecessary demand for evidence; the fourth let an uppercase
    host through unmeasured, which is the gate not firing at all."""
    validator = _validator()
    assert validator._host_matches(uri, validator.PROBEABLE_HOSTS) is matches


# --- what the mutation catalogue found on 2026-08-29 --------------------------------------
# Rules 9-14 were covered by 73 tests and by no mutant. Four mutations survived all of them.


def test_losing_exactly_one_anchor_is_refused_by_the_floor() -> None:
    """M314: `actual < minimum` weakened to `actual < minimum - 1` survived every test here,
    because the only floor test deletes eighteen probes and eleven anchors at once. A ratchet
    that tolerates losing one piece of evidence per commit is not a ratchet.

    The count is driven to exactly `minimum - 1` rather than "one fewer than today", so this
    keeps separating the two predicates as the catalog grows past its recorded floor.
    """
    catalog = _catalog()
    floor = int(catalog["evidence_floor"]["integrity_anchored"])
    anchored = [e for e in catalog["sources"] if e.get("integrity_anchor")]
    assert len(anchored) >= floor, "the catalog already sits below its own recorded floor"
    for entry in anchored[: len(anchored) - floor + 1]:
        entry.pop("integrity_anchor")

    result = _validator().evaluate(catalog)
    assert result["summary"]["integrity_anchored"] == floor - 1
    assert result["status"] == "FAIL"
    assert any(
        f"integrity_anchored: {floor - 1} is below the recorded floor of {floor}" in p
        for p in result["problems"]
    ), result["problems"]


def test_the_gate_entry_point_applies_the_mandatory_evidence_rule() -> None:
    """M320: every rule-14 negative control calls `_mandatory_evidence_problems` itself, so
    deleting its call from `evaluate` disconnected the rule from the gate with all 73 tests
    still green. The rule existed, and ran nowhere."""
    catalog = _catalog()
    unmeasured = _valid_entry()
    unmeasured["id"] = "TEST-UNMEASURED-ON-A-PROBEABLE-HOST"
    unmeasured["source_uri"] = "https://zakon.rada.gov.ua/laws/show/548-14/print"
    catalog["sources"].append(unmeasured)

    result = _validator().evaluate(catalog)
    assert result["status"] == "FAIL"
    assert any("carries no content_probe" in p for p in result["problems"]), result["problems"]


def test_the_gate_entry_point_applies_the_per_entry_rules() -> None:
    """M321: the same hole one function over, and a wider one — rules 1-13 are reached only
    through `_entry_problems`, which every negative control calls directly. Dropping its call
    from `evaluate` left the catalog gate checking ids for duplication and nothing else."""
    catalog = _catalog()
    restricted = _valid_entry()
    restricted["id"] = "TEST-RESTRICTED-AND-INGESTIBLE"
    restricted["classification"] = "restricted"
    catalog["sources"].append(restricted)

    result = _validator().evaluate(catalog)
    assert result["status"] == "FAIL"
    assert any("classification=restricted but ingestible=true" in p for p in result["problems"]), (
        result["problems"]
    )


def test_a_probe_with_no_date_at_all_is_refused() -> None:
    """M339: freshness reads `probed_on`, and nothing tested that it has to be there. A probe
    with the field deleted is never stale — the same act-repealed-tomorrow hole rule 14 closed
    for old dates, reopened by removing the date."""
    entry = _probed_entry()
    entry["content_probe"].pop("probed_on")
    problems = _validator()._entry_problems(entry)
    assert any("records no probe date" in p for p in problems), problems


def test_lowering_the_floor_is_refused_on_its_own_terms() -> None:
    """`actual < minimum` compares the count with the floor and never the floor with what it
    used to be, so one commit that lowers the floor and deletes the evidence together passes.

    Rule 14 happens to catch that today, because every anchor sits on a host it covers — but
    that is a property of the current catalog, not of this rule. One probe on a host in
    neither list and the protection is gone.
    """
    validator = _validator()
    committed = validator._floor_lowered_problems({"content_probed": 1, "total": 1}, {})
    assert committed, "a floor lowered below the committed one produced no problem"
    assert any("was lowered from" in p for p in committed)

    unchanged = validator._floor_lowered_problems(_catalog()["evidence_floor"], _catalog())
    assert unchanged == [], f"the committed floor flags itself: {unchanged}"


def test_the_floor_ratchet_still_holds_without_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unpacked release archive has no Git, and that is the artefact an auditor reads.

    Verified 2026-08-29 by replacing `git` with `exit 127`: a floor lowered from 28 to 5
    gave exit 1 with Git and exit 0 without — the ratchet was disabled in exactly the place
    it mattered most. The catalog now carries its own history, which travels with the
    archive.
    """
    validator = _validator()
    monkeypatch.setattr(
        validator.subprocess,
        "run",
        lambda *args, **kwargs: type("R", (), {"returncode": 127, "stdout": b""})(),
    )
    recorded, origin = validator._committed_floor()
    assert origin == "catalog_history", "without Git the floor has no witness at all"
    assert isinstance(recorded, dict) and recorded

    lowered = dict(_catalog()["evidence_floor"])
    lowered["content_probed"] = 1
    problems = validator._floor_lowered_problems(lowered, {})
    assert any("was lowered from" in p for p in problems), problems
    assert any("catalog_history" in p for p in problems)


def test_an_unverifiable_floor_says_so_instead_of_passing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No Git and no history is a third state, not silence — the shape of SCOPE_UNDECLARED."""
    validator = _validator()
    monkeypatch.setattr(
        validator.subprocess,
        "run",
        lambda *args, **kwargs: type("R", (), {"returncode": 127, "stdout": b""})(),
    )
    catalog = _catalog()
    catalog.pop("evidence_floor_history", None)
    # Inside ROOT: _committed_floor derives the Git path from CATALOG.relative_to(ROOT).
    stripped = ROOT / "var" / "catalog-without-history.json"
    stripped.parent.mkdir(exist_ok=True)
    stripped.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(validator, "CATALOG", stripped)

    problems = validator._floor_lowered_problems(catalog["evidence_floor"], catalog)
    assert any("cannot be checked against any previous value" in p for p in problems), problems
    assert any("origin=unverifiable" in p for p in problems)


def test_one_capture_may_not_anchor_two_sources() -> None:
    """CAPTURE_ROOT narrowed "any file in the repository" to "any file under config/corpus"
    and stopped there. Pointing one source at another's capture passed: path inside the root,
    digest matching, and a snapshot of a different page standing in as evidence for this one.
    All twelve mod.gov.ua sources could have shared a single file."""
    catalog = _catalog()
    anchored = [e for e in catalog["sources"] if isinstance(e.get("integrity_anchor"), dict)]
    assert len(anchored) >= 2, "the catalog has too few anchors for this test"
    anchored[0]["integrity_anchor"] = copy.deepcopy(anchored[1]["integrity_anchor"])

    result = _validator().evaluate(catalog)
    assert result["status"] == "FAIL"
    assert any("is claimed by 2 sources" in p for p in result["problems"]), result["problems"]


def test_a_404_page_above_the_byte_floor_is_still_refused() -> None:
    """Bytes were the wrong unit. A real government 404 carries navigation, a footer and a
    style block — 1.2 KB of HTML that cleared a 512-byte floor holding no document at all."""
    fake = ROOT / "config/corpus/attachments/__wordy_404__.html"
    fake.write_text(
        "<html><head><style>" + "a{color:red}" * 60 + "</style></head><body>"
        "<nav>Головна Про нас Контакти</nav><h1>404</h1><footer>© 2026</footer></body></html>",
        encoding="utf-8",
    )
    try:
        assert fake.stat().st_size > 512, "this fixture must clear the old byte floor"
        entry = _attached_entry()
        anchor = entry["attachment_anchors"][0]
        anchor["path"] = "config/corpus/attachments/__wordy_404__.html"
        anchor["sha256"] = _digest_of(anchor["path"])
        anchor["extractor_supports_format"] = True
        problems = _validator()._entry_problems(entry)
        assert any("once tags are stripped" in p for p in problems), problems
    finally:
        fake.unlink()


def test_a_suffix_this_gate_cannot_inspect_is_refused() -> None:
    """A 16-byte file named .bin passed every rule: no signature list, no archive member and
    no text check applied to it, so nothing looked at its contents at all."""
    fake = ROOT / "config/corpus/attachments/__opaque__.bin"
    fake.write_bytes(b"<html>404</html>")
    try:
        entry = _attached_entry()
        anchor = entry["attachment_anchors"][0]
        anchor["path"] = "config/corpus/attachments/__opaque__.bin"
        anchor["sha256"] = _digest_of(anchor["path"])
        anchor["extractor_supports_format"] = False
        anchor["unreadable_content_survey"] = {
            "words": 40,
            "opening": "щось, що конвертер зміг прочитати з нечитаного формату",
            "surveyed_with": "LibreOffice 24.2",
            "surveyed_on": _today(),
        }
        entry["content_probe"]["required_attachments"] = [anchor["uri"]]
        problems = _validator()._entry_problems(entry)
        assert any("cannot inspect" in p for p in problems), problems
    finally:
        fake.unlink()


@pytest.mark.parametrize(
    ("written", "accepted"),
    [
        ("2026-08-29", True),
        # The most common way to write when a measurement was taken. date.fromisoformat
        # refuses it and said "is not an ISO date", which sends the reader to look for a
        # defect in the data rather than in the parser.
        ("2026-08-29T10:00:00", True),
        ("2026-08-29T10:00:00+00:00", True),
        # Both name a real day and neither is written by any probe here: their appearance
        # is a data error, and silently accepting them hid that.
        ("20260829", False),
        ("2026-W35-6", False),
        ("не дата", False),
    ],
)
def test_the_same_moment_written_differently(written: str, accepted: bool) -> None:
    """An equivalent-input probe, not a poison: every live date in the catalog is
    YYYY-MM-DD, so no corruption of the data could have exposed this. Only the same moment
    written another way could."""
    from iso_dates import iso_date

    if accepted:
        assert iso_date(written).isoformat() == "2026-08-29"
    else:
        with pytest.raises(ValueError):
            iso_date(written)


def test_the_floor_fallback_survives_a_history_of_mixed_shapes() -> None:
    """A second entry shape turned the gitless fallback off in silence.

    `evidence_floor_history` holds two kinds of entry: a snapshot `{on, floor, note}` and
    a deliberate change `{on, from, to, reason}`. The fallback read `history[-1]["floor"]`,
    so one change entry appended on top made it None and the ratchet reported
    `origin=unverifiable`. Never visible in the tree, where Git answers first — and the
    fallback exists precisely for where Git does not: an unpacked archive.
    """
    import importlib.util

    script = ROOT / "scripts/validate_doctrine_catalog.py"
    spec = importlib.util.spec_from_file_location("validate_doctrine_catalog_probe", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    history = json.loads(module.CATALOG.read_text(encoding="utf-8"))["evidence_floor_history"]
    assert len(history) >= 2, "one entry cannot show the mixed-shape failure"
    assert not isinstance(history[-1].get("floor"), dict), (
        "the last entry now carries a floor, so this test no longer reproduces the case "
        "it exists for — pick another fixture rather than deleting the check"
    )
    recorded, origin = module._committed_floor()
    assert origin in {"git", "catalog_history"}, origin
    assert isinstance(recorded, dict) and recorded, recorded


@pytest.mark.parametrize(
    ("name", "change", "expected"),
    [
        ("ключ зник", "drop", "зник із підлоги"),
        ("ключ знижено", 1, "was lowered from"),
        ("ключ став рядком", "72", "перестав бути цілим"),
        ("ключ став True", True, "перестав бути цілим"),
    ],
)
def test_a_floor_key_cannot_be_removed_or_untyped_in_silence(
    name: str, change: object, expected: str
) -> None:
    """Порівняння лише там, де ОБИДВА значення цілі, робило видалення ключа тихим способом
    зняти з нього ратчет: `document_probed`, `page_probed`, `attachments_captured` можна
    було прибрати без жодного слова. Правило про обов'язкові ключі рятувало лише два.

    Знайдено 2026-08-30 паралельною сесією, і правило одразу спіймало реальне зникнення:
    `ingestible_total` (166) справді випав із підлоги під час перенесення лічильників.
    """
    import importlib.util

    script = ROOT / "scripts/validate_doctrine_catalog.py"
    spec = importlib.util.spec_from_file_location("vdc_floor_probe", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    recorded, _origin = module._committed_floor()
    assert isinstance(recorded, dict) and "document_probed" in recorded, recorded
    declared = dict(recorded)
    if change == "drop":
        declared.pop("document_probed")
    else:
        declared["document_probed"] = change
    # Порожній каталог: ліцензувати зниження нічим, тож правило міряється саме.
    problems = module._floor_lowered_problems(declared, {})
    assert any(expected in problem for problem in problems), (name, problems)
    # Дуальність: незмінена підлога не сміє давати жодної скарги.
    assert module._floor_lowered_problems(dict(recorded), {}) == []


def test_lowering_the_floor_needs_a_licence_naming_the_key_and_both_numbers() -> None:
    """Ратчет мусив би заборонити, а не змусити брехати.

    `ingestible_total` міряє РОЗМІР КОРПУСУ, а не кількість доказів: він падає рівно тоді,
    коли ми стаємо чеснішими — зняли 404, зняли те, що сервер відмовляє, зняли за грифом.
    Тричі за добу підлога зупиняла паралельну сесію: двічі справедливо, а на третій раз
    дізнатися, що сервер відмовляє, — це поповнення знання, і ратчет читав його як втрату.

    Тому не «не можна», а «не мовчки»: зниження ліцензується записом в історії, який
    називає САМЕ цей ключ, ОБИДВА числа й причину. Тиха зміна лишається неможливою.
    """
    import importlib.util

    script = ROOT / "scripts/validate_doctrine_catalog.py"
    spec = importlib.util.spec_from_file_location("vdc_licence_probe", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    reason = "причина, достатньо довга, щоб бути реченням, яке хтось прочитає, а не заповнювачем"
    licensed = {
        "evidence_floor_history": [
            {"on": "2026-08-30", "from": {"k": 10}, "to": {"k": 9}, "reason": reason}
        ]
    }
    assert module._licensed_lowering(licensed, "k", 10, 9)
    # Заповнювач замість причини не ліцензує.
    short = {"evidence_floor_history": [{"from": {"k": 10}, "to": {"k": 9}, "reason": "бо так"}]}
    assert not module._licensed_lowering(short, "k", 10, 9)
    # Числа мусять збігтися рівно: запис про інше зниження не ліцензує це.
    other = {
        "evidence_floor_history": [
            {"from": {"k": 99}, "to": {"k": 9}, "reason": reason},
            {"from": {"j": 10}, "to": {"j": 9}, "reason": reason},
        ]
    }
    assert not module._licensed_lowering(other, "k", 10, 9)
    # Історії немає — ліцензувати нічим.
    assert not module._licensed_lowering({}, "k", 10, 9)


def test_a_partial_change_does_not_shadow_the_full_floor_snapshot() -> None:
    """Часткова зміна затінювала повний знімок, і ратчет мовчав про решту ключів.

    Історія має дві форми: знімок `{on, floor, note}` і зміну `{on, from, to, reason}`,
    і `to` буває частковим — один ключ. Читання «останнього запису з підлогою» після
    запису про `ingestible_total` лишало фолбек із рівно одним лічильником: без Git
    ратчет на `content_probed` і `attachments_captured` не тримав нічого. Відновлення:
    останній повний знімок плюс кожна пізніша зміна по ключах.
    """
    import importlib.util

    script = ROOT / "scripts/validate_doctrine_catalog.py"
    spec = importlib.util.spec_from_file_location("vdc_rebuild_probe", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    history = json.loads(module.CATALOG.read_text(encoding="utf-8"))["evidence_floor_history"]
    last = history[-1]
    assert isinstance(last.get("to"), dict) and "floor" not in last, (
        "останній запис більше не є частковою зміною — проба перестала відтворювати випадок"
    )
    assert len(last["to"]) < 3, "часткова зміна мусить називати менше ключів, ніж знімок"

    recorded, origin = module._committed_floor()
    assert isinstance(recorded, dict)
    # Ключі повного знімка мусять пережити часткову зміну зверху.
    for key in ("content_probed", "attachments_captured", "governing_authority", "total"):
        assert key in recorded, (key, origin, sorted(recorded))
