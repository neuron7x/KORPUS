from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

EXCLUDED_PARTS = {".git", "dist", "var", "node_modules", ".venv", "__pycache__", ".pytest_cache"}
EXCLUDED_FILES = {"REPOSITORY_MANIFEST.json", ".coverage"}


def _included(relative: Path) -> bool:
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if relative.name in EXCLUDED_FILES or relative.name.startswith(".coverage."):
        return False
    return not (relative.parts[:2] == ("infra", "secrets") and relative.suffix == ".txt")


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
    return sorted((path for path in paths if _included(path)), key=lambda value: value.as_posix())


def _archive_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if _included(relative):
            paths.append(relative)
    return sorted(paths, key=lambda value: value.as_posix())


def release_paths(root: Path) -> list[Path]:
    """Return reproducible release paths.

    In a Git worktree, only tracked/staged files are authoritative. In a gitless
    archive, every non-excluded file is part of the snapshot by construction.
    """

    return _git_tracked_paths(root) or _archive_paths(root)


def build_manifest(root: Path) -> dict[str, object]:
    records = []
    for relative in release_paths(root):
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"release path is missing: {relative.as_posix()}")
        content = path.read_bytes()
        records.append(
            {
                "path": relative.as_posix(),
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    root_digest = hashlib.sha256(
        "".join(f'{item["path"]}\0{item["sha256"]}\n' for item in records).encode()
    ).hexdigest()
    return {
        "schema": "korpus.repository-manifest.v3",
        "file_count": len(records),
        "root_sha256": root_digest,
        "files": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = build_manifest(root)
    (root / "REPOSITORY_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = {"file_count": manifest["file_count"], "root_sha256": manifest["root_sha256"]}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
