from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PREFIXES = (".git/", "var/", "dist/", "reports/", ".pytest_cache/", "apps/web/dist/")
EXCLUDED_NAMES = {"REPOSITORY_MANIFEST.json"}


def _included(relative: str) -> bool:
    return relative not in EXCLUDED_NAMES and not relative.startswith(EXCLUDED_PREFIXES)


def _git_tracked_files() -> tuple[list[Path], str] | None:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
        )
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
        ).stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    values = listed.stdout.decode("utf-8").split("\0")
    return ([ROOT / value for value in values if value and _included(value)], commit)


def _archive_files() -> tuple[list[Path], str]:
    manifest_path = ROOT / "REPOSITORY_MANIFEST.json"
    if not manifest_path.is_file():
        raise RuntimeError("neither Git metadata nor REPOSITORY_MANIFEST.json is available")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = manifest.get("files")
    root_hash = manifest.get("root_sha256")
    if not isinstance(records, list) or not isinstance(root_hash, str) or len(root_hash) != 64:
        raise RuntimeError("invalid repository manifest")
    paths: list[Path] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise RuntimeError("invalid repository manifest record")
        relative = record["path"]
        if not _included(relative):
            continue
        path = (ROOT / relative).resolve()
        if ROOT not in path.parents or not path.is_file():
            raise RuntimeError(f"manifest source file is missing or unsafe: {relative}")
        expected = record.get("sha256")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected != actual:
            raise RuntimeError(f"manifest source hash mismatch: {relative}")
        paths.append(path)
    return paths, f"archive:{root_hash}"


def tracked_files() -> tuple[list[Path], str]:
    return _git_tracked_files() or _archive_files()


def build() -> dict[str, object]:
    paths, source_revision = tracked_files()
    entries: list[dict[str, object]] = []
    for path in sorted(paths):
        relative = path.relative_to(ROOT).as_posix()
        payload = path.read_bytes()
        entries.append(
            {"path": relative, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        )
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema": "korpus-system-manifest-v1",
        "commit": source_revision,
        "files": entries,
        "file_count": len(entries),
        "manifest_root_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("var/system-manifest.json"))
    args = parser.parse_args()
    result = build()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
