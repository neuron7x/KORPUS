from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from manifest_lib.integrity import file_sha256, manifest_failures
elif __package__:
    from .manifest_lib.integrity import file_sha256, manifest_failures
else:
    from manifest_lib.integrity import file_sha256, manifest_failures

if __package__:
    from .regular_file_boundary import regular_paths, walk_regular_paths
else:
    from regular_file_boundary import regular_paths, walk_regular_paths

MANIFEST_NAME = "DISTRIBUTION_MANIFEST.json"
RECEIPT_NAME = "FULL_SSOT_PACKAGE_RECEIPT.json"
RECEIPT_SCHEMA = "korpus.full-ssot-package-receipt.v4"
_RECEIPT_STATIC = {
    "schema": RECEIPT_SCHEMA,
    "status": "PASS",
    "status_scope": "ARCHIVE_INTEGRITY_ONLY",
    "provenance_status": "NOT_ADMITTED",
    "provenance_reason": "GITLESS_PACKAGE_HAS_NO_EXTERNAL_TRUST_ANCHOR",
    "package_role": "FULL_SSOT_CANONICAL",
    "history_included": False,
    "distribution_manifest_policy": "receipt_excluded_exact_manifest_binding",
}
MANIFEST_KEYS = {
    "schema",
    "kind",
    "manifest_self_excluded",
    "file_count",
    "root_sha256",
    "files",
}
RECORD_KEYS = {"path", "bytes", "sha256", "mode"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MODE = re.compile(r"^0[0-7]{3}$")
_NTFS_DOTGIT = re.compile(r"(?:\.git|git~1)[ .]*(?::[\s\S]*)?\Z", re.IGNORECASE)
_NTFS_GITMODULES = re.compile(
    r"(?:\.gitmodules|gitmod~[1-4]|~[1-9][0-9]{6}|g~[1-9][0-9]{5}|"
    r"gi~[1-9][0-9]{4}|gi7~[1-9][0-9]{3}|gi7e~[1-9][0-9]{2}|"
    r"gi7eb~[1-9][0-9]|gi7eba~[1-9])[ .]*(?::[\s\S]*)?\Z",
    re.IGNORECASE,
)
_HFS_IGNORED = str.maketrans(
    "",
    "",
    "\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e"
    "\u206a\u206b\u206c\u206d\u206e\u206f\ufeff",
)

EXCLUDED_PARTS = {".git", "dist", "var", "node_modules", ".venv", "__pycache__", ".pytest_cache"}
SOURCE_GENERATED_PREFIXES = {
    ("reports",),
    # Журнал вироків — запис ПРО дерево, у тому самому класі, що reports/. Поки він був
    # у складі digest'а, кожен дописаний вирок зсував source_tree_sha256 і робив
    # `handoff --require-bound` STALE: звіт описував дерево, яке щойно перестало бути цим.
    # Дві сесії за добу по черзі втрачали 15-хвилинні прогони на цьому, і вигравав той,
    # хто писав останнім, а не той, хто правий. Твердження про систему не сміє мінятися
    # разом із самою системою — інакше воно не може її описувати.
    (".verdict-ledger.jsonl",),
    ("handoff", "evidence"),
    ("evidence",),
    ("PACKAGE_BOUNDARY.md",),
    ("PACKAGE_BUILD.json",),
    ("FULL_SSOT_PACKAGE_RECEIPT.json",),
    ("CANONICAL_RELEASE_REPORT.json",),
    ("CANONICAL_RELEASE_REPORT.md",),
}
LOCAL_EXCLUDED_FILES, MANIFEST_NAMES = (
    {".coverage", ".korpus-source-root"},
    {"SOURCE_MANIFEST.json", "DISTRIBUTION_MANIFEST.json", "REPOSITORY_MANIFEST.json"},
)
PRESERVED_PACKAGE_PAIR = {
    ("LINEAGE", "v0.9.7-original-uploaded", MANIFEST_NAME),
    ("LINEAGE", "v0.9.7-original-uploaded", RECEIPT_NAME),
}


def json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def git_metadata_path(value: object) -> bool:
    if isinstance(value, str):
        path = PurePosixPath(value)
    elif isinstance(value, Path | PurePosixPath):
        path = PurePosixPath(value.as_posix())
    else:
        return False
    parts = path.parts
    return any(_dotgit_component(part) for part in parts) or (
        bool(parts) and _gitmodules_component(parts[-1])
    )


def _dotgit_component(part: str) -> bool:
    return (
        _NTFS_DOTGIT.fullmatch(part) is not None
        or part.translate(_HFS_IGNORED).casefold() == ".git"
    )


def _gitmodules_component(part: str) -> bool:
    return (
        _NTFS_GITMODULES.fullmatch(part) is not None
        or part.translate(_HFS_IGNORED).casefold() == ".gitmodules"
    )


def _canonical_relative(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and path.as_posix() == value and ".." not in path.parts


def _valid_record(record: dict[str, Any]) -> bool:
    size, digest, mode = record.get("bytes"), record.get("sha256"), record.get("mode")
    return (
        set(record) == RECORD_KEYS
        and _canonical_relative(record.get("path"))
        and not git_metadata_path(record.get("path"))
        and isinstance(size, int)
        and not isinstance(size, bool)
        and size >= 0
        and isinstance(digest, str)
        and HEX64.fullmatch(digest) is not None
        and isinstance(mode, str)
        and MODE.fullmatch(mode) is not None
    )


def _manifest_header_failures(manifest: dict[str, Any]) -> list[str]:
    failures = (
        ["distribution manifest fields are not exact"] if set(manifest) != MANIFEST_KEYS else []
    )
    identity = (
        manifest.get("schema"),
        manifest.get("kind"),
        manifest.get("manifest_self_excluded"),
    )
    if identity != ("korpus.distribution-manifest.v2", "distribution", True):
        failures.append("invalid distribution manifest schema")
    return failures


def _record_failures(raw_records: list[object], records: list[dict[str, Any]]) -> list[str]:
    failures = (
        ["invalid distribution manifest record shape"] if len(records) != len(raw_records) else []
    )
    paths = [str(row["path"]) for row in records]
    if paths != sorted(paths):
        failures.append("distribution manifest paths are not sorted")
    duplicates = sorted(path for path, count in Counter(paths).items() if count > 1)
    if duplicates:
        failures.append(f"duplicate distribution manifest paths: {duplicates}")
    return failures


def _aggregate_failures(
    manifest: dict[str, Any], records: list[dict[str, Any]], *, complete: bool
) -> list[str]:
    failures: list[str] = []
    count, root_digest = manifest.get("file_count"), manifest.get("root_sha256")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        failures.append("invalid distribution manifest file count")
    if not isinstance(root_digest, str) or HEX64.fullmatch(root_digest) is None:
        failures.append("invalid distribution manifest root digest")
    return [*failures, *manifest_failures(manifest, records)] if complete else failures


def distribution_manifest_contract(
    root: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[str]]:
    manifest = json_object(root / MANIFEST_NAME)
    if manifest is None:
        return {}, {}, ["distribution manifest is missing or invalid JSON"]
    failures = _manifest_header_failures(manifest)
    raw_records = manifest.get("files")
    if not isinstance(raw_records, list):
        return manifest, {}, [*failures, "invalid distribution manifest records"]
    records = [row for row in raw_records if isinstance(row, dict) and _valid_record(row)]
    failures.extend(_record_failures(raw_records, records))
    failures.extend(
        _aggregate_failures(manifest, records, complete=len(records) == len(raw_records))
    )
    index = {str(record["path"]): record for record in records}
    return manifest, index, failures


def _count_files(path: Path) -> int:
    return sum(candidate.is_file() for candidate in path.rglob("*")) if path.is_dir() else 0


def _source_release_identity(root: Path) -> tuple[Path, str, str, int] | None:
    source_path = root / "SOURCE_MANIFEST.json"
    source = json_object(source_path)
    release = json_object(root / "apps/api/src/korpus/release.json")
    if source is None or release is None or not source_path.is_file():
        return None
    tag, version = release.get("tag"), release.get("version")
    source_root, source_files = source.get("root_sha256"), source.get("file_count")
    if (
        source.get("schema") != "korpus.source-manifest.v2"
        or source.get("kind") != "source"
        or not isinstance(source_root, str)
        or HEX64.fullmatch(source_root) is None
        or not isinstance(source_files, int)
        or isinstance(source_files, bool)
        or source_files < 1
        or not isinstance(version, str)
        or not version
        or tag != f"v{version}"
    ):
        return None
    return source_path, tag, source_root, source_files


def expected_full_ssot_receipt(root: Path, manifest: dict[str, Any]) -> dict[str, object] | None:
    identity = _source_release_identity(root)
    if identity is None:
        return None
    source_path, tag, source_root, source_files = identity
    return {
        **_RECEIPT_STATIC,
        "failures": [],
        "release": tag,
        "source_manifest_sha256": file_sha256(source_path),
        "source_manifest_root_sha256": source_root,
        "source_manifest_files": source_files,
        "web_dist_files": _count_files(root / "apps/web/dist"),
        "lineage_files": _count_files(root / "LINEAGE"),
        "distribution_manifest_sha256": file_sha256(root / MANIFEST_NAME),
        "distribution_manifest_root_sha256": manifest.get("root_sha256"),
        "distribution_records": manifest.get("file_count"),
    }


def source_included(relative: Path) -> bool:
    checks = (
        not git_metadata_path(relative),
        not any(part in EXCLUDED_PARTS for part in relative.parts),
        not any(relative.parts[: len(prefix)] == prefix for prefix in SOURCE_GENERATED_PREFIXES),
        relative.name not in LOCAL_EXCLUDED_FILES,
        not relative.name.startswith(".coverage."),
        relative.parts in PRESERVED_PACKAGE_PAIR
        or relative.name not in {*MANIFEST_NAMES, RECEIPT_NAME},
        relative.suffix != ".bundle",
        not (relative.parts[:2] == ("infra", "secrets") and relative.suffix == ".txt"),
    )
    return all(checks)


def _git_tracked_paths(root: Path) -> list[Path] | None:
    try:
        probe = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            check=True,
            capture_output=True,
            text=True,
        )
        if probe.stdout.strip() != "true":
            return None
        output = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    paths = [Path(item.decode("utf-8")) for item in output.split(b"\0") if item]
    included = [path for path in paths if source_included(path)]
    return regular_paths(root, included, "tracked source path")


def _walk_files(root: Path, predicate: Callable[[Path], bool]) -> list[Path]:
    return walk_regular_paths(root, predicate, "manifest path")


def source_paths(root: Path) -> list[Path]:
    """Committed/staged source paths in a worktree; source paths in a gitless snapshot."""
    tracked = _git_tracked_paths(root)
    return tracked if tracked is not None else _walk_files(root, source_included)


def distribution_paths(root: Path) -> list[Path]:
    """Exact payload paths; the manifest and its dependent receipt stay outside the DAG."""
    excluded = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache"}
    return _walk_files(
        root,
        lambda relative: (
            not any(part in excluded for part in relative.parts)
            and not git_metadata_path(relative)
            and relative.as_posix() not in {MANIFEST_NAME, RECEIPT_NAME}
        ),
    )
