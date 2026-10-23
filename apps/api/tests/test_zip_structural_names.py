"""Offline ZIP metadata namespace invariants; never extract archive payloads."""

from __future__ import annotations

import zipfile

import pytest

from scripts.zip_safety import _canonical_name, _record_entry, _structural_collision_failures


def _failures(names: tuple[str, ...]) -> list[str]:
    exact: set[str] = set()
    folded: dict[str, str] = {}
    files: set[str] = set()
    directories: set[str] = set()
    failures: list[str] = []
    for name in names:
        failures.extend(_record_entry(zipfile.ZipInfo(name), exact, folded, files, directories))
    return failures + _structural_collision_failures(files, directories)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize(
    "names",
    [
        ("foo.", "foo/bar.txt"),
        ("FOO", "foo/bar.txt"),
        ("foo?", "foo_/bar.txt"),
        ("parent./child", "parent/child/deep.txt"),
        ("reports /leaf", "reports/leaf/deep.txt"),
        ("foo.", "foo/bar/"),
        ("foo", "foo/bar/"),
        ("foo?", "foo_/bar/"),
        ("UPPER", "upper/deep/"),
    ],
)
def test_normalized_file_prefixes_are_refused(names: tuple[str, ...], reverse: bool) -> None:
    result = _failures(tuple(reversed(names)) if reverse else names)
    assert any("prefix collision" in failure for failure in result)


@pytest.mark.parametrize("names", [("foo.", "foo/"), ("FOO", "foo/"), ("foo?", "foo_/")])
def test_normalized_file_directory_aliases_are_refused(names: tuple[str, ...]) -> None:
    assert _failures(names)


@pytest.mark.parametrize("component", ["", ".", "..", ". ", " ... ", "   "])
def test_empty_normalized_components_remain_refused(component: str) -> None:
    canonical, failure = _canonical_name("root/" + component + "/leaf")
    assert canonical is None and failure is not None


@pytest.mark.parametrize(
    "names",
    [
        ("tree/", "tree/a.txt", "tree/b.txt"),
        ("tree/branch/", "other.txt"),
        ("one.txt", "two.txt"),
        ("unicode/", "unicode/caf\u00e9.txt"),
        ("dir with spaces/a.txt", "dir with spaces/b.txt"),
    ],
)
def test_distinct_safe_names_remain_admissible(names: tuple[str, ...]) -> None:
    assert _failures(names) == []
