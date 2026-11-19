"""Small neutral, internally complete packages for artifact-boundary tests."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from collections.abc import Mapping
from pathlib import Path

from korpus.application.provenance import evidence_source_path_included

from scripts.manifest_lib.integrity import manifest_root
from scripts.manifest_paths import source_included
from scripts.snapshot_assurance import SOURCES

RELEASE = "apps/api/src/korpus/release.json"
SOURCE = "SOURCE_MANIFEST.json"
RESEARCH = "reports/RESEARCH_ASSURANCE_REPORT.json"
SNAPSHOT = "reports/ASSURANCE_SNAPSHOT.json"
TAG = "v0.0.0"


def encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True) + "\n").encode()


def record(name: str, body: bytes, mode: int = 0o644) -> dict[str, object]:
    return {
        "path": name,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "mode": f"{mode:04o}",
    }


def manifest(records: list[dict[str, object]], kind: str) -> bytes:
    return encoded(
        {
            "schema": f"korpus.{kind}-manifest.v2",
            "kind": kind,
            "manifest_self_excluded": True,
            "file_count": len(records),
            "root_sha256": manifest_root(records),
            "files": records,
        }
    )


def _source_digest(files: Mapping[str, bytes], *, evidence: bool) -> str:
    # Fixture framing follows the published format, not the new consumer helper.
    digest = hashlib.sha256(b"korpus-source-digest-v2\0" if evidence else b"")
    for name, body in sorted(files.items()):
        if not source_included(Path(name)):
            continue
        if evidence and not evidence_source_path_included(name):
            continue
        path = name.encode()
        digest.update(len(path).to_bytes(4, "big") + path)
        digest.update(len(body).to_bytes(8, "big") + body)
    return digest.hexdigest()


def resnapshot(files: dict[str, bytes]) -> None:
    report = json.loads(files[RESEARCH])
    records = [
        {key: value for key, value in record(name, files[name]).items() if key != "mode"}
        for name in sorted([RESEARCH, *(f"reports/{name}" for name in SOURCES)])
    ]
    files[SNAPSHOT] = encoded(
        {
            "schema": "korpus.assurance-snapshot.v1",
            "status": "PASS",
            "release": TAG,
            "records": records,
            "limitations": report.get("limitations", []),
        }
    )


def package_files(
    extra: Mapping[str, bytes] | None = None, *, modes: Mapping[str, int] | None = None
) -> dict[str, bytes]:
    files = {
        RELEASE: encoded(
            {
                "schema": "korpus.release-identity.v1",
                "product": "KORPUS",
                "version": "0.0.0",
                "tag": TAG,
                "artifact_stem": "neutral-package",
                "distribution_artifact": "neutral-package.zip",
            }
        ),
        "apps/api/src/example.py": b"VALUE = 1\n",
        **(extra or {}),
    }
    modes = modes or {}
    records = [
        record(name, body, 0o755 if modes.get(name, 0o644) & 0o111 else 0o644)
        for name, body in sorted(files.items())
        if source_included(Path(name))
    ]
    files[SOURCE] = manifest(records, "source")
    for name in SOURCES:
        files[f"reports/{name}"] = b"<synthetic/>\n" if name.endswith(".xml") else b"{}\n"
    files[RESEARCH] = encoded(
        {
            "status": "PASS",
            "source_tree_sha256": _source_digest(files, evidence=False),
            "evidence_source_sha256": _source_digest(files, evidence=True),
            "limitations": ["Neutral fixture; no release or production authorization."],
        }
    )
    resnapshot(files)
    return files


def write_package(
    archive: Path,
    files: Mapping[str, bytes],
    *,
    prefix: str = "KORPUS/",
    modes: Mapping[str, int] | None = None,
    stored_modes: Mapping[str, int] | None = None,
) -> int:
    modes = modes or {}
    stored_modes = stored_modes or modes
    members = dict(files)
    records = [record(name, body, modes.get(name, 0o644)) for name, body in sorted(members.items())]
    members["DISTRIBUTION_MANIFEST.json"] = manifest(records, "distribution")
    with zipfile.ZipFile(archive, "w") as target:
        for name, body in members.items():
            info = zipfile.ZipInfo(prefix + name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | stored_modes.get(name, 0o644)) << 16
            target.writestr(info, body)
    return len(members)
