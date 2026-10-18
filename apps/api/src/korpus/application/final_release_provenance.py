from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from korpus.application.github_release_context import (
    CANONICAL_GITHUB_REPOSITORY,
    GIT_SHA,
    POSITIVE_INTEGER,
)

BUILD_TYPE = "https://korpus.dev/buildtypes/canonical-release-zip/v1"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
REQUIRED_BUILD_MATERIALS = (
    "SOURCE_MANIFEST.json",
    "apps/api/src/korpus/release.json",
    "apps/api/requirements.runtime.lock",
    "apps/api/requirements.dev.lock",
    "apps/web/package-lock.json",
    "apps/api/Dockerfile",
    "apps/web/Dockerfile",
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ReleaseBuildContext:
    release: str
    source_commit_sha: str
    github_run_id: str
    github_run_attempt: str
    expected_materials: Mapping[str, str]
    verification_time: datetime


def _builder_parts(
    statement: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any], Mapping[str, Any]]:
    predicate = statement.get("predicate")
    predicate = predicate if isinstance(predicate, Mapping) else {}
    definition = predicate.get("buildDefinition")
    definition = definition if isinstance(definition, Mapping) else {}
    run = predicate.get("runDetails")
    run = run if isinstance(run, Mapping) else {}
    builder = run.get("builder")
    builder = builder if isinstance(builder, Mapping) else {}
    return str(builder.get("id", "")), definition, run


def _subject_bound(statement: Mapping[str, Any], artifact_name: str, artifact_sha256: str) -> bool:
    subjects = statement.get("subject")
    if not isinstance(subjects, list) or len(subjects) != 1 or not isinstance(subjects[0], Mapping):
        return False
    digest = subjects[0].get("digest")
    return (
        subjects[0].get("name") == artifact_name
        and isinstance(digest, Mapping)
        and digest.get("sha256") == artifact_sha256
    )


def _material_entry(item: object) -> tuple[str, str] | None:
    if not isinstance(item, Mapping) or set(item) != {"uri", "digest"}:
        return None
    uri, digest = item.get("uri"), item.get("digest")
    if not isinstance(uri, str) or not isinstance(digest, Mapping) or set(digest) != {"sha256"}:
        return None
    sha = digest.get("sha256")
    return (uri, sha) if isinstance(sha, str) else None


def _resolved_materials_bound(
    definition: Mapping[str, Any], expected_materials: Mapping[str, str]
) -> bool:
    canonical_uris = {f"file:///{relative}" for relative in REQUIRED_BUILD_MATERIALS}
    expected = dict(expected_materials)
    if set(expected) != canonical_uris or not all(
        isinstance(value, str) and SHA256.fullmatch(value) for value in expected.values()
    ):
        return False
    resolved = definition.get("resolvedDependencies")
    if not isinstance(resolved, list) or len(resolved) != len(expected):
        return False
    entries = [_material_entry(item) for item in resolved]
    if any(entry is None for entry in entries):
        return False
    actual = {entry[0]: entry[1] for entry in entries if entry is not None}
    return len(actual) == len(entries) and actual == expected


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _timestamps_bound(run: Mapping[str, Any], verification_time: datetime) -> bool:
    metadata = run.get("metadata")
    if not isinstance(metadata, Mapping):
        return False
    started, finished = (
        _timestamp(metadata.get("startedOn")),
        _timestamp(metadata.get("finishedOn")),
    )
    if started is None or finished is None or verification_time.utcoffset() is None:
        return False
    return verification_time - timedelta(
        hours=2
    ) <= started <= finished <= verification_time + timedelta(
        minutes=5
    ) and finished - started <= timedelta(minutes=90)


def builder_provenance_checks(
    statement: Mapping[str, Any],
    artifact_name: str,
    artifact_sha: str,
    source_manifest_sha: str,
    trusted_builder_ids: Collection[str],
    context: ReleaseBuildContext,
) -> tuple[str, dict[str, bool]]:
    builder_id, definition, run = _builder_parts(statement)
    external = definition.get("externalParameters")
    external = external if isinstance(external, Mapping) else {}
    metadata = run.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    source_valid = bool(GIT_SHA.fullmatch(context.source_commit_sha))
    run_valid = bool(
        POSITIVE_INTEGER.fullmatch(context.github_run_id)
        and POSITIVE_INTEGER.fullmatch(context.github_run_attempt)
    )
    builder = (
        f"https://github.com/{CANONICAL_GITHUB_REPOSITORY}/.github/workflows/"
        f"release.yml@refs/tags/{context.release}"
    )
    invocation = (
        f"https://github.com/{CANONICAL_GITHUB_REPOSITORY}/actions/runs/"
        f"{context.github_run_id}/attempts/{context.github_run_attempt}"
    )
    return builder_id, {
        "builder_statement_type": (
            statement.get("_type") == STATEMENT_TYPE
            and statement.get("predicateType") == PREDICATE_TYPE
        ),
        "builder_provenance_verified": (
            _subject_bound(statement, artifact_name, artifact_sha)
            and external.get("release") == context.release
            and external.get("sourceManifestSha256") == source_manifest_sha
        ),
        "builder_build_type": definition.get("buildType") == BUILD_TYPE,
        "builder_source_commit": source_valid
        and external.get("sourceCommit") == context.source_commit_sha,
        "builder_materials_bound": _resolved_materials_bound(
            definition, context.expected_materials
        ),
        "builder_invocation_bound": run_valid and metadata.get("invocationId") == invocation,
        "builder_timestamps_valid": _timestamps_bound(run, context.verification_time),
        "builder_trusted": builder_id == builder and builder_id in set(trusted_builder_ids),
    }


def release_manifest_checks(
    manifest: Mapping[str, Any],
    artifact_name: str,
    artifact_sha: str,
    source_manifest_sha: str,
    production_assurance_sha: str,
    context: ReleaseBuildContext,
) -> dict[str, bool]:
    return {
        "release_manifest_bound": (
            manifest.get("release") == context.release
            and manifest.get("artifact") == artifact_name
            and manifest.get("artifact_sha256") == artifact_sha
            and manifest.get("source_manifest_sha256") == source_manifest_sha
            and manifest.get("production_assurance_sha256") == production_assurance_sha
        ),
        "release_manifest_git_commit": bool(GIT_SHA.fullmatch(context.source_commit_sha))
        and manifest.get("git_commit") == context.source_commit_sha,
    }
