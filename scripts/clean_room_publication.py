from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def git_config(root: Path, name: str) -> str:
    completed = subprocess.run(
        ["git", "config", "--get", name], cwd=root, capture_output=True, text=True, check=False
    )
    value = completed.stdout.strip()
    if completed.returncode or not value:
        raise SystemExit(f"git {name} is required for clean-room attestation")
    return value


def _sign(root: Path, report: Path, key: str) -> None:
    signature = report.with_name(report.name + ".sig")
    signature.unlink(missing_ok=True)
    completed = subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", key, "-n", "korpus-clean-room", str(report)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode or not signature.is_file():
        raise SystemExit(f"clean-room attestation signing failed: {completed.stderr[-400:]}")


def publish(
    root: Path,
    relative: str,
    payload: dict[str, Any],
    junit: bytes,
    signer: str,
    key: str,
    mirror: tuple[dict[str, Any], bytes] | None,
) -> None:
    output = root / relative
    junit_path = output.with_suffix(".junit.xml")
    payload.update(
        {
            "attested_by": signer,
            "attestation_class": "OWNER_ATTESTED",
            "junit_path": junit_path.relative_to(root).as_posix(),
            "junit_sha256": hashlib.sha256(junit).hexdigest(),
        }
    )
    if mirror is not None:
        mirror_payload, mirror_junit = mirror
        mirror_path = output.with_suffix(".mirror.junit.xml")
        payload["mirror"] = {
            "remote": mirror_payload["remote"],
            "source_tree_sha256": mirror_payload["source_tree_sha256"],
            "status": mirror_payload["status"],
            "digests_agree": mirror_payload["source_tree_sha256"] == payload["source_tree_sha256"],
            "junit_path": mirror_path.relative_to(root).as_posix(),
            "junit_sha256": hashlib.sha256(mirror_junit).hexdigest(),
        }
        mirror_path.parent.mkdir(parents=True, exist_ok=True)
        mirror_path.write_bytes(mirror_junit)
        if not payload["mirror"]["digests_agree"]:
            payload["status"] = "FAIL"
    output.parent.mkdir(parents=True, exist_ok=True)
    junit_path.write_bytes(junit)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _sign(root, output, key)
