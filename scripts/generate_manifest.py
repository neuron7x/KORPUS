from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

EXCLUDED_PARTS = {".git", "dist", "var", "node_modules", ".venv", "__pycache__", ".pytest_cache"}
EXCLUDED_FILES = {"REPOSITORY_MANIFEST.json"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    records = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if relative.name in EXCLUDED_FILES or (relative.parts[:2] == ("infra", "secrets") and relative.suffix == ".txt"):
            continue
        content = path.read_bytes()
        records.append({
            "path": relative.as_posix(),
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        })
    root_digest = hashlib.sha256(
        "".join(f'{item["path"]}\0{item["sha256"]}\n' for item in records).encode()
    ).hexdigest()
    manifest = {
        "schema": "korpus.repository-manifest.v2",
        "file_count": len(records),
        "root_sha256": root_digest,
        "files": records,
    }
    (root / "REPOSITORY_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"file_count": len(records), "root_sha256": root_digest}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
