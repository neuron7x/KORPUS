from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PREFIXES = (".git/", "var/", "dist/", "reports/", ".pytest_cache/", "apps/web/dist/")
EXCLUDED_NAMES = {"REPOSITORY_MANIFEST.json"}


def tracked_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    )
    values = completed.stdout.decode("utf-8").split("\0")
    return [ROOT / value for value in values if value]


def build() -> dict[str, object]:
    entries: list[dict[str, object]] = []
    for path in sorted(tracked_files()):
        relative = path.relative_to(ROOT).as_posix()
        if relative in EXCLUDED_NAMES or relative.startswith(EXCLUDED_PREFIXES):
            continue
        payload = path.read_bytes()
        entries.append(
            {"path": relative, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        )
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    return {
        "schema": "korpus-system-manifest-v1",
        "commit": commit,
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
