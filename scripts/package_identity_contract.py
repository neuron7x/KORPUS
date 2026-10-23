from __future__ import annotations

import re
from collections.abc import Mapping

BUILD_FIELDS = frozenset(["schema", "release", "source_manifest_root_sha256", "history_included", "source_commit", "import_required_to_obtain_git_commit", "derived_from_source_commit"])  # fmt: skip
RELEASE_FIELDS = frozenset(["schema", "product", "version", "tag", "artifact_stem", "distribution_artifact"])  # fmt: skip
SAFE_STEM = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def safe_artifact_stem(value: object) -> bool:
    return isinstance(value, str) and bool(SAFE_STEM.fullmatch(value))


def valid_release_identity(release: Mapping[str, object]) -> bool:
    version, tag = release.get("version"), release.get("tag")
    stem, artifact = release.get("artifact_stem"), release.get("distribution_artifact")
    return (
        set(release) == RELEASE_FIELDS
        and release.get("schema") == "korpus.release-identity.v1"
        and release.get("product") == "KORPUS"
        and isinstance(version, str)
        and bool(version)
        and tag == f"v{version}"
        and safe_artifact_stem(stem)
        and artifact == f"{stem}.zip"
    )
