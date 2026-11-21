"""Bind a native upload invocation without conflating adjacent whole-second steps."""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from github_evidence_artifact import (  # noqa: E402
    _upload_log,
    admit_artifact,
    artifact_inventory,
)
from github_evidence_run import SQLITE, UPLOAD_ACTION, admit_run  # noqa: E402

from .hosted_evidence_fixtures import (  # noqa: E402
    SELECTED,
    EvidenceFixture,
    measured_fixture,
)

NATIVE = json.loads((Path(__file__).parent / "fixtures/github_upload_window_v7.json").read_bytes())[
    "cases"
]
POSTGRES = NATIVE[1]
HEADER = "##[group]Run " + UPLOAD_ACTION
DIGEST = "SHA256 digest of uploaded artifact is " + POSTGRES["artifact"]["digest"][7:]
FINAL = "Artifact coverage-postgres-1 successfully finalized. Artifact ID 14576640600"
# The five recorded lines are the header, name, metadata end, digest and finalization.
FIRST_UPLOAD = POSTGRES["log_excerpt"].splitlines()[:5]
SECOND_UPLOAD = POSTGRES["log_excerpt"].splitlines()[5:]


def _verify(lines: list[str]) -> None:
    _upload_log(("\n".join(lines) + "\n").encode(), POSTGRES["artifact"], POSTGRES["upload"])


@pytest.mark.parametrize("sample", NATIVE, ids=[sample["producer"] for sample in NATIVE])
def test_recorded_native_upload_keeps_exact_binding_despite_rounded_step_times(
    sample: dict[str, Any],
) -> None:
    _upload_log(sample["log_excerpt"].encode(), sample["artifact"], sample["upload"])


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (HEADER, "##[group]Run actions/upload-artifact@" + "f" * 40),
        (DIGEST, "SHA256 digest of uploaded artifact is " + "f" * 64),
        (FINAL, FINAL.replace("14576640600", "999")),
        (FINAL, FINAL.replace("coverage-postgres-1", "foreign-artifact-1")),
        (DIGEST, "prefix " + DIGEST),
        (FINAL, FINAL + " suffix"),
    ],
    ids=["pin", "digest", "id", "name", "digest-prefix", "finalization-suffix"],
)
def test_selected_native_upload_requires_exact_identity_strings(old: str, new: str) -> None:
    payload = "\n".join(FIRST_UPLOAD)
    assert payload.count(old) == 1
    with pytest.raises(ValueError, match="authenticated producer log"):
        _verify(payload.replace(old, new).splitlines())


@pytest.mark.parametrize("index", [3, 4], ids=["digest", "finalization"])
def test_selected_invocation_rejects_duplicated_evidence_lines(index: int) -> None:
    lines = FIRST_UPLOAD.copy()
    lines.insert(index, lines[index])
    with pytest.raises(ValueError, match="authenticated producer log"):
        _verify(lines)


@pytest.mark.parametrize("foreign_digest", [False, True])
def test_selected_artifact_finalization_cannot_appear_in_two_invocations(
    foreign_digest: bool,
) -> None:
    second = [
        line.replace("postgres-diagnostics-1", "coverage-postgres-1").replace(
            "14576960067", "14576640600"
        )
        for line in SECOND_UPLOAD
    ]
    if not foreign_digest:
        second[3] = second[3].partition(" ")[0] + " " + DIGEST
    with pytest.raises(ValueError, match="authenticated producer log"):
        _verify([*FIRST_UPLOAD, *second])


@pytest.mark.parametrize(
    "next_header",
    [
        "##[group]Run actions/upload-artifact@" + "f" * 40,
        "##[group]Run actions/download-artifact@" + "f" * 40,
        "##[group]Run python -m unrelated_step",
    ],
    ids=["foreign-pin", "other-action", "shell-step"],
)
@pytest.mark.parametrize("index", [3, 4], ids=["before-digest", "before-finalization"])
def test_expected_upload_events_cannot_be_spliced_across_invocations(
    next_header: str, index: int
) -> None:
    lines = FIRST_UPLOAD.copy()
    instant = "2026-11-19T21:21:09.0000000Z" if index == 3 else "2026-11-19T21:21:10.0000000Z"
    lines.insert(index, instant + " " + next_header)
    with pytest.raises(ValueError, match="authenticated producer log"):
        _verify(lines)


def test_digest_and_finalization_cannot_cross_two_pinned_invocations() -> None:
    lines = FIRST_UPLOAD.copy()
    lines.insert(4, "2026-11-19T21:21:10.0000000Z " + HEADER)
    with pytest.raises(ValueError, match="authenticated producer log"):
        _verify(lines)


def test_adjacent_pinned_invocation_can_own_both_selected_outputs() -> None:
    lines = FIRST_UPLOAD.copy()
    lines.insert(3, "2026-11-19T21:21:09.0000000Z " + HEADER)
    _verify(lines)


@pytest.mark.parametrize("order", [[3, 0, 1, 2, 4], [0, 1, 2, 4, 3]])
def test_native_upload_identity_events_must_remain_in_order(order: list[int]) -> None:
    with pytest.raises(ValueError, match=r"producer (log|upload log)"):
        _verify([FIRST_UPLOAD[index] for index in order])


@pytest.mark.parametrize("index", [0, 3, 4], ids=["header", "digest", "finalization"])
@pytest.mark.parametrize("instant", ["2026-11-19T21:21:07.999Z", "2026-11-19T21:21:11Z"])
def test_every_selected_identity_event_remains_inside_the_original_step_window(
    index: int, instant: str
) -> None:
    lines = FIRST_UPLOAD.copy()
    lines[index] = instant + " " + lines[index].partition(" ")[2]
    with pytest.raises(ValueError, match="authenticated producer log"):
        _verify(lines)


def test_existing_final_second_margin_and_metadata_endgroup_remain_valid() -> None:
    lines = FIRST_UPLOAD.copy()
    assert lines[2].endswith("##[endgroup]")
    lines[4] = "2026-11-19T21:21:10.999Z " + FINAL
    _verify(lines)


def test_unrelated_upload_may_have_identical_zip_bytes_without_owning_selected_id() -> None:
    second = SECOND_UPLOAD.copy()
    second[3] = second[3].partition(" ")[0] + " " + DIGEST
    _verify([*FIRST_UPLOAD, *second])


@pytest.fixture(scope="module")
def measured(tmp_path_factory: pytest.TempPathFactory) -> EvidenceFixture:
    return measured_fixture(tmp_path_factory.mktemp("github-upload-invocations"))


def _fixture_log(fixture: EvidenceFixture, message: str, offset: int) -> bytes:
    instant = (fixture.upload_time + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")
    return f"{instant} {message}\n".encode()


def test_artifact_admission_accepts_an_adjacent_upload_without_relaxing_download_binding(
    measured: EvidenceFixture,
) -> None:
    fixture = measured.clone()
    key = "/actions/jobs/101/logs"
    fixture.api.responses[key] += _fixture_log(fixture, HEADER, 3)
    fixture.api.responses[key] += _fixture_log(fixture, "##[endgroup]", 3)
    fixture.api.responses[key] += _fixture_log(
        fixture, "SHA256 digest of uploaded artifact is " + "f" * 64, 4
    )
    fixture.api.responses[key] += _fixture_log(
        fixture, "Artifact unrelated-2 successfully finalized. Artifact ID 999", 4
    )
    run = admit_run(fixture.api, SELECTED, fixture.checkout)
    artifact = admit_artifact(fixture.api, run, SQLITE, artifact_inventory(fixture.api, run))
    assert artifact.archive_sha256 == fixture.artifacts[SQLITE.job]["digest"][7:]
    assert fixture.api.downloads == [key, "/actions/artifacts/201/zip"]


def test_artifact_download_rejects_cross_invocation_log_splicing(measured: EvidenceFixture) -> None:
    fixture = measured.clone()
    key = "/actions/jobs/101/logs"
    lines = fixture.api.responses[key].splitlines(keepends=True)
    lines.insert(2, _fixture_log(fixture, "##[group]Run python -m unrelated_step", 1))
    fixture.api.responses[key] = b"".join(lines)
    run = admit_run(fixture.api, SELECTED, fixture.checkout)
    with pytest.raises(ValueError, match="authenticated producer log"):
        admit_artifact(fixture.api, run, SQLITE, artifact_inventory(fixture.api, run))
    assert fixture.api.downloads == [key]
