#!/usr/bin/env python3
"""Verify that dependency resolution is reproducible, exact and policy-complete.

The lock verifier is intentionally offline. It proves properties of the lock material
that are knowable from the repository itself: exact version pins, SHA-256 artifact hashes,
no VCS/direct/local references, closure of declared direct dependencies, and web lock
parity. Known-vulnerability status is a different claim and remains delegated to an OSV
scanner; this script emits the exact OSV query batch so the external scan is reproducible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT)]

from korpus.application.provenance import compute_source_digest  # noqa: E402

from scripts.release_identity import release_tag  # noqa: E402

_LOCK_LINE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\\\s]+)\s*\\?$")
_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})$")
_UNSAFE_PREFIXES = ("-e ", "--editable ", "git+", "hg+", "svn+", "bzr+", "file:", "http:", "https:")


@dataclass(frozen=True, slots=True)
class LockedRequirement:
    name: str
    version: str
    hashes: tuple[str, ...]
    source: str

    @property
    def canonical_name(self) -> str:
        return canonicalize_name(self.name)


@dataclass(frozen=True, slots=True)
class LockParseResult:
    requirements: tuple[LockedRequirement, ...]
    files: tuple[Path, ...]
    failures: tuple[str, ...]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _consume_requirement(
    path: Path,
    lines: list[str],
    index: int,
    raw: str,
) -> tuple[LockedRequirement | None, int, list[str]]:
    failures: list[str] = []
    if raw.startswith(_UNSAFE_PREFIXES) or " @ " in raw or ";" in raw:
        return None, index, [f"{path}:{index}: non-hermetic requirement: {raw}"]
    match = _LOCK_LINE.match(raw)
    if not match:
        while index < len(lines) and lines[index].lstrip().startswith("--hash="):
            index += 1
        return None, index, [f"{path}:{index}: requirement is not an exact == pin: {raw}"]

    name, version = match.groups()
    hashes: list[str] = []
    while index < len(lines):
        candidate = lines[index].strip().rstrip("\\").strip()
        if not candidate.startswith("--hash="):
            break
        index += 1
        hash_match = _HASH.match(candidate)
        if hash_match:
            hashes.append(hash_match.group(1))
        else:
            failures.append(f"{path}:{index}: only sha256 hashes are accepted: {candidate}")
    if not hashes:
        failures.append(f"{path}:{index}: {name}=={version} has no sha256 artifact hash")
    try:
        Version(version)
    except InvalidVersion:
        failures.append(f"{path}:{index}: invalid version: {name}=={version}")
    requirement = LockedRequirement(name, version, tuple(sorted(set(hashes))), str(path))
    return requirement, index, failures


def _parse_lock(path: Path, seen: set[Path] | None = None) -> LockParseResult:
    seen = set() if seen is None else seen
    resolved = path.resolve()
    if resolved in seen:
        return LockParseResult((), (), (f"recursive requirement include: {path}",))
    seen.add(resolved)
    if not path.is_file():
        return LockParseResult((), (), (f"missing lock file: {path}",))

    failures: list[str] = []
    requirements: list[LockedRequirement] = []
    files = [path]
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        raw = lines[index].strip()
        index += 1
        if not raw or raw.startswith("#"):
            continue
        if raw.startswith("-r ") or raw.startswith("--requirement "):
            nested = _parse_lock((path.parent / raw.split(maxsplit=1)[1].strip()).resolve(), seen)
            requirements.extend(nested.requirements)
            files.extend(nested.files)
            failures.extend(nested.failures)
            continue
        requirement, index, line_failures = _consume_requirement(path, lines, index, raw)
        failures.extend(line_failures)
        if requirement is not None:
            requirements.append(requirement)

    return LockParseResult(tuple(requirements), tuple(files), tuple(failures))


def _index(
    requirements: Iterable[LockedRequirement],
) -> tuple[dict[str, LockedRequirement], list[str]]:
    index: dict[str, LockedRequirement] = {}
    failures: list[str] = []
    for item in requirements:
        key = item.canonical_name
        prior = index.get(key)
        if prior is not None and prior.version != item.version:
            failures.append(
                f"conflicting pins for {key}: {prior.version} ({prior.source}) vs {item.version} ({item.source})"
            )
            continue
        if prior is None:
            index[key] = item
    return index, failures


def _declared_dependencies(pyproject: Path) -> dict[str, list[str]]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    result = {"runtime": list(project.get("dependencies", []))}
    for group, values in (project.get("optional-dependencies", {}) or {}).items():
        result[str(group)] = list(values)
    return result


def _check_declared(
    declared: list[str], locked: dict[str, LockedRequirement], label: str
) -> list[str]:
    failures: list[str] = []
    for text in declared:
        requirement = Requirement(text)
        key = canonicalize_name(requirement.name)
        item = locked.get(key)
        if item is None:
            failures.append(
                f"{label}: direct dependency {requirement.name} is absent from lock closure"
            )
            continue
        if requirement.specifier and Version(item.version) not in requirement.specifier:
            failures.append(
                f"{label}: lock {item.name}=={item.version} violates declared constraint {requirement.specifier}"
            )
    return failures


def _check_web(package_json: Path, package_lock: Path) -> tuple[list[str], dict[str, object]]:
    failures: list[str] = []
    package = json.loads(package_json.read_text(encoding="utf-8"))
    lock = json.loads(package_lock.read_text(encoding="utf-8"))
    if lock.get("lockfileVersion") != 3:
        failures.append("web: package-lock.json must use lockfileVersion 3")
    root = (lock.get("packages") or {}).get("") or {}
    for field in ("dependencies", "devDependencies", "optionalDependencies"):
        declared = package.get(field) or {}
        recorded = root.get(field) or {}
        if declared != recorded:
            failures.append(f"web: package.json/{field} differs from package-lock root")
    packages = lock.get("packages") or {}
    for path, record in packages.items():
        if path == "":
            continue
        resolved = str(record.get("resolved", ""))
        integrity = str(record.get("integrity", ""))
        if resolved.startswith(("git+", "file:", "http:")):
            failures.append(f"web: non-hermetic package source {path}: {resolved}")
        if not integrity.startswith("sha512-"):
            failures.append(f"web: package {path} lacks sha512 integrity")
    return failures, {
        "lockfile_version": lock.get("lockfileVersion"),
        "packages": max(len(packages) - 1, 0),
    }


def verify(root: Path = ROOT) -> dict[str, object]:
    runtime_path = root / "apps/api/requirements.runtime.lock"
    dev_path = root / "apps/api/requirements.dev.lock"
    pyproject = root / "apps/api/pyproject.toml"
    runtime = _parse_lock(runtime_path)
    dev = _parse_lock(dev_path)
    runtime_index, runtime_index_failures = _index(runtime.requirements)
    dev_index, dev_index_failures = _index(dev.requirements)
    declared = _declared_dependencies(pyproject)

    failures = [
        *runtime.failures,
        *dev.failures,
        *runtime_index_failures,
        *dev_index_failures,
        *_check_declared(declared["runtime"], runtime_index, "runtime"),
        *_check_declared(declared.get("dev", []), dev_index, "dev"),
        *_check_declared(declared.get("postgres", []), dev_index, "postgres"),
    ]
    web_failures, web_summary = _check_web(
        root / "apps/web/package.json", root / "apps/web/package-lock.json"
    )
    failures.extend(web_failures)

    # Exact OSV input is emitted but not interpreted as a vulnerability result. An
    # external scanner can consume this batch without resolving dependencies again.
    osv_queries = [
        {
            "package": {"ecosystem": "PyPI", "name": item.name},
            "version": item.version,
        }
        for item in sorted(runtime_index.values(), key=lambda item: item.canonical_name)
    ]
    report: dict[str, object] = {
        "schema": "korpus.dependency-lock-verification.v2",
        "status": "PASS" if not failures else "FAIL",
        "release": release_tag(),
        "source_tree_sha256": compute_source_digest(root),
        "python": {
            "runtime_packages": len(runtime_index),
            "dev_closure_packages": len(dev_index),
            "runtime_lock_sha256": sha256(runtime_path),
            "dev_lock_sha256": sha256(dev_path),
            "direct_runtime_dependencies": len(declared["runtime"]),
            "direct_dev_dependencies": len(declared.get("dev", [])),
            "direct_postgres_dependencies": len(declared.get("postgres", [])),
            "all_pins_exact": not any("not an exact == pin" in item for item in failures),
            "all_artifacts_sha256_bound": not any("has no sha256" in item for item in failures),
        },
        "web": web_summary,
        "osv_query_batch": {"queries": osv_queries},
        "vulnerability_status": "UNKNOWN_UNTIL_OSV_OR_EQUIVALENT_SCANNER_EXECUTES",
        "failures": failures,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--osv-out", type=Path)
    args = parser.parse_args()
    report = verify(args.root.resolve())
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.osv_out:
        args.osv_out.parent.mkdir(parents=True, exist_ok=True)
        args.osv_out.write_text(
            json.dumps(report["osv_query_batch"], indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
