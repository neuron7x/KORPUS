"""Verify inner claims solely from the already admitted private ZIP extraction."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path

from assurance_snapshot_contract import complete_snapshot_records
from korpus.application.final_release_evidence import strict_signed_json_object
from korpus.application.provenance import digest_source_records, evidence_source_path_included
from manifest_lib.source_verification import source_manifest_failures
from manifest_paths import source_included
from path_admission import regular_file
from release_identity import release_tag
from research_assurance_verification import research_assurance_failures
from source_digest import digest_tree_records


def _load(root: Path, relative: str) -> dict[str, object]:
    path = root / relative
    if not regular_file(path):
        raise ValueError(f"missing or symlinked packaged member: {relative}")
    return dict(strict_signed_json_object(path.read_bytes(), relative))


def _source_records(root: Path, inventory: Mapping[str, str]) -> Iterator[tuple[str, bytes]]:
    for name in sorted(inventory):
        yield name, (root / name).read_bytes()


def _research_failures(root: Path, inventory: Mapping[str, str]) -> list[str]:
    # Strict JSON admission precedes the existing release identity validator.
    _load(root, "apps/api/src/korpus/release.json")
    release = release_tag(root)
    full_digest = digest_tree_records(
        (Path(name), content) for name, content in _source_records(root, inventory)
    )
    evidence_digest = digest_source_records(
        (name, content)
        for name, content in _source_records(root, inventory)
        if evidence_source_path_included(name)
    )
    assurance = _load(root, "reports/RESEARCH_ASSURANCE_REPORT.json")
    snapshot = _load(root, "reports/ASSURANCE_SNAPSHOT.json")
    evidence_failure = (
        None
        if assurance.get("evidence_source_sha256") == evidence_digest
        else "assurance evidence source digest does not match packaged source"
    )
    return research_assurance_failures(
        assurance,
        snapshot,
        release,
        full_digest,
        evidence_failure,
        bool(complete_snapshot_records(root, snapshot.get("records"))),
        "packaged source",
    )


def package_contract_failures(
    root: Path, modes: Mapping[str, str], prior_failures: list[str]
) -> list[str]:
    if prior_failures:
        return prior_failures  # Inner claims cannot repair a failed outer inventory.
    # Git normalizes source permissions to executable/non-executable. ZIP extraction
    # does not retain these bits, so the admitted ZIP inventory is authoritative.
    inventory = {
        name: "0755" if int(mode, 8) & 0o111 else "0644"
        for name, mode in modes.items()
        if source_included(Path(name))
    }
    failures, _ = source_manifest_failures(root, inventory)
    if failures:
        return failures
    try:
        return _research_failures(root, inventory)
    except (OSError, RuntimeError, ValueError) as error:
        return [f"packaged research evidence invalid: {error}"]
