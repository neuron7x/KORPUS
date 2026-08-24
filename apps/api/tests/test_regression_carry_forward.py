from __future__ import annotations

from scripts.verify_regression_carry_forward import diff_records


def test_diff_records_classifies_added_removed_and_modified_without_overlap() -> None:
    old = {"same": "a", "modified": "b", "removed": "c"}
    new = {"same": "a", "modified": "d", "added": "e"}
    added, removed, modified = diff_records(old, new)
    assert added == ("added",)
    assert removed == ("removed",)
    assert modified == ("modified",)


def test_diff_records_is_deterministic() -> None:
    old = {"z": "1", "a": "1"}
    new = {"z": "2", "b": "1"}
    assert diff_records(old, new) == (("b",), ("a",), ("z",))
