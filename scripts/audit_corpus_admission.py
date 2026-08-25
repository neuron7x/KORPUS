#!/usr/bin/env python3
"""Fail closed unless every corpus byte has a complete, matching governance envelope."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INGESTIBLE = {".txt", ".md", ".json", ".html", ".htm", ".pdf", ".docx"}
REQUIRED = (
    "file",
    "source_sha256",
    "canonical_title",
    "issuer",
    "revision",
    "authority",
    "data_owner_id",
    "rights_reference",
    "rights_status",
    "classification",
    "releasability",
    "retention_policy_id",
    "access_policy_id",
    "source_uri",
)
ADMISSIBLE_RIGHTS = {"open", "licensed", "authorized"}


def _issue(code: str, file: str, detail: str) -> dict[str, str]:
    return {"code": code, "file": file, "detail": detail}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _resolved_file(root: Path, name: str) -> Path | None:
    candidate = root / name
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() and not candidate.is_symlink() else None


def _entry_issues(entry: object, root: Path, sentinel: str) -> list[dict[str, str]]:
    if not isinstance(entry, dict):
        return [_issue("ENTRY_TYPE", "<unknown>", "entry must be an object")]
    name = str(entry.get("file", "<missing>"))
    issues = []
    missing = [field for field in REQUIRED if not entry.get(field) or entry.get(field) == sentinel]
    if missing:
        issues.append(_issue("GOVERNANCE_INCOMPLETE", name, ",".join(missing)))
    path = _resolved_file(root, name)
    if path is None:
        issues.append(_issue("FILE_BOUNDARY", name, "missing, symlinked, or outside root"))
        return issues
    declared = str(entry.get("source_sha256", ""))
    actual = _sha256_file(path)
    if declared != actual:
        issues.append(_issue("HASH_MISMATCH", name, f"declared={declared or '<missing>'}"))
    if entry.get("rights_status") not in ADMISSIBLE_RIGHTS:
        issues.append(_issue("RIGHTS_NOT_ADMISSIBLE", name, str(entry.get("rights_status"))))
    return issues


def _duplicate_issues(values: list[str], code: str) -> list[dict[str, str]]:
    counts = Counter(value for value in values if value)
    return [
        _issue(code, value, "listed more than once")
        for value, count in sorted(counts.items())
        if count > 1
    ]


def _unlisted_issues(
    manifest: dict[str, Any], root: Path, described: set[str]
) -> list[dict[str, str]]:
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and path.suffix.casefold() in INGESTIBLE
    }
    manifest_path = str(manifest.get("manifest_file", ""))
    excluded = {manifest_path} if manifest_path else set()
    return [
        _issue("UNLISTED_FILE", name, "ingestible file lacks governance")
        for name in sorted(actual - described - excluded)
    ]


def evaluate(manifest: dict[str, Any], root: Path) -> dict[str, Any]:
    entries = manifest.get("documents")
    if not isinstance(entries, list) or not entries:
        return {
            "schema": "korpus.corpus-admission.v1",
            "status": "FAIL",
            "issues": [_issue("EMPTY_MANIFEST", "<manifest>", "documents must be non-empty")],
        }
    sentinel = str(manifest.get("review_sentinel", "REVIEW_REQUIRED"))
    issues = [issue for entry in entries for issue in _entry_issues(entry, root, sentinel)]
    names = [str(entry.get("file", "")) for entry in entries if isinstance(entry, dict)]
    hashes = [str(entry.get("source_sha256", "")) for entry in entries if isinstance(entry, dict)]
    issues.extend(_duplicate_issues(names, "DUPLICATE_PATH"))
    issues.extend(_duplicate_issues(hashes, "DUPLICATE_CONTENT"))
    issues.extend(_unlisted_issues(manifest, root, set(names)))
    complete = sum(not _entry_issues(entry, root, sentinel) for entry in entries)
    return {
        "schema": "korpus.corpus-admission.v1",
        "status": "PASS" if not issues else "FAIL",
        "documents": len(entries),
        "admission_ready": complete,
        "admission_ratio": round(complete / len(entries), 6),
        "issue_counts": {
            code: sum(i["code"] == code for i in issues)
            for code in sorted({i["code"] for i in issues})
        },
        "issues": issues,
        "interpretation": "PASS proves manifest completeness and byte binding, not legal authority or human approval.",
    }


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, encoding="utf-8"
    ) as stream:
        temporary = Path(stream.name)
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "reports/CORPUS_ADMISSION_CURRENT.json")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest["manifest_file"] = (
        args.manifest.resolve().relative_to(args.root.resolve()).as_posix()
        if args.manifest.resolve().is_relative_to(args.root.resolve())
        else ""
    )
    report = evaluate(manifest, args.root)
    _atomic_write(args.out, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
