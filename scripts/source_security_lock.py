"""Deterministic application lock inventory, separate from scanner discovery."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

PIN = re.compile(r"([A-Za-z0-9_.-]+)==([^\\\s]+)(?:\s+\\)?")
HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}(?:\s+\\)?")
LOCK_PATHS = {kind: f"apps/api/requirements.{kind}.lock" for kind in ("runtime", "dev", "scanners")}


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def direct_pins(root: Path, kind: str) -> dict[str, tuple[str, str]]:
    """Read only exact hashed pins; an unknown directive cannot shrink the census."""
    result: dict[str, tuple[str, str]] = {}
    pending = False
    for raw in (root / LOCK_PATHS[kind]).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if HASH.fullmatch(line):
            if not result:
                raise ValueError("lock hash precedes a package")
            pending = False
            continue
        if pending:
            raise ValueError("lock package has no SHA256")
        if kind == "dev" and line == "-r requirements.runtime.lock":
            continue
        match = PIN.fullmatch(line)
        if match is None or canonical_name(match[1]) in result:
            raise ValueError("unsupported or duplicate lock requirement")
        result[canonical_name(match[1])] = (match[1], match[2])
        pending = True
    if pending or not result:
        raise ValueError("empty or unhashed dependency lock")
    return result


def locked_packages(root: Path, kind: str) -> dict[str, str]:
    pins = direct_pins(root, "scanners" if kind == "scanners" else "runtime")
    if kind == "dev":
        for name, value in direct_pins(root, "dev").items():
            if name in pins and pins[name][1] != value[1]:
                raise ValueError("runtime and development pins disagree")
            pins[name] = value
    elif kind not in {"runtime", "scanners"}:
        raise ValueError("unknown lock scope")
    return {name: version for name, (_display, version) in pins.items()}


def build_lock_sbom(root: Path) -> dict[str, Any]:
    """The exact application lock universe; not a tree or container scan."""
    locked_packages(root, "dev")
    components: dict[tuple[str, str], dict[str, str]] = {}
    for kind, scope in (("dev", "excluded"), ("runtime", "required")):
        for key, (name, version) in direct_pins(root, kind).items():
            components[(key, version)] = {
                "type": "library",
                "name": name,
                "version": version,
                "scope": scope,
                "purl": f"pkg:pypi/{key}@{version}",
            }
    seed = "\n".join(f"{name}=={version}" for name, version in sorted(components))
    serial = uuid5(NAMESPACE_URL, "korpus-lock-sbom:v1\n" + seed)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "serialNumber": serial.urn,
        "metadata": {"component": {"type": "application", "name": "korpus-api"}},
        "components": [components[key] for key in sorted(components)],
    }
