from __future__ import annotations
import pytest
from korpus.application.pec_cohort import validate_complete_cohort

def test_complete_cohort_passes_only_exact_set():
    v=validate_complete_cohort(["a","b"],[{"case_id":"b"},{"case_id":"a"}])
    assert v.complete and not v.missing and not v.unexpected

def test_cohort_rejects_cherry_picked_missing_case():
    v=validate_complete_cohort(["a","b"],[{"case_id":"a"}])
    assert not v.complete and v.missing==("b",)

def test_cohort_rejects_unexpected_case():
    v=validate_complete_cohort(["a"],[{"case_id":"a"},{"case_id":"x"}])
    assert not v.complete and v.unexpected==("x",)

def test_cohort_rejects_duplicate_expected_ids():
    with pytest.raises(ValueError, match="unique"): validate_complete_cohort(["a","a"],[])
