from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from korpus.application.github_assurance_receipts import sha256_bytes
from korpus.application.release_claim_hosted import (
    TRUSTED_ROOT_PATH,
    TRUSTED_ROOT_SHA256,
    allowed_source_ref,
)
from korpus.application.release_claim_sigstore_command import sigstore_command

VERIFIER_CONFIG_PATH = "config/assurance/sigstore-verifier.json"
VERIFIER_PATH = "/usr/bin/gh"
VERIFIER_VERSION = "2.100.0"
VERIFIER_SHA256 = "553949e2efa12842771efe6012aa4de21f1d591530ec17fc435f610f10e017ee"


def verifier_executable(root: Path) -> tuple[str | None, str | None]:
    expected = {
        "schema": "korpus.sigstore-verifier.v1",
        "path": VERIFIER_PATH,
        "version": VERIFIER_VERSION,
        "sha256": VERIFIER_SHA256,
    }
    try:
        config = json.loads((root / VERIFIER_CONFIG_PATH).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "SIGSTORE_VERIFIER_CONFIG_INVALID"
    if config != expected:
        return None, "SIGSTORE_VERIFIER_CONFIG_INVALID"
    try:
        metadata = os.lstat(VERIFIER_PATH)
    except OSError:
        return None, "SIGSTORE_VERIFIER_NOT_REGULAR"
    if not stat.S_ISREG(metadata.st_mode):
        return None, "SIGSTORE_VERIFIER_NOT_REGULAR"
    if metadata.st_uid != 0:
        return None, "SIGSTORE_VERIFIER_NOT_ROOT_OWNED"
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        return None, "SIGSTORE_VERIFIER_MUTABLE"
    try:
        digest = sha256_bytes(Path(VERIFIER_PATH).read_bytes())
    except OSError:
        return None, "SIGSTORE_VERIFIER_UNREADABLE"
    if digest != VERIFIER_SHA256:
        return None, "SIGSTORE_VERIFIER_DIGEST_MISMATCH"
    try:
        version = subprocess.run(
            [VERIFIER_PATH, "--version"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, "SIGSTORE_VERIFIER_VERSION_UNAVAILABLE"
    first_line = version.stdout.splitlines()[0] if version.stdout else ""
    match = re.fullmatch(r"gh version ([0-9]+\.[0-9]+\.[0-9]+)(?: .*)?", first_line)
    if version.returncode != 0 or match is None or match.group(1) != VERIFIER_VERSION:
        return None, "SIGSTORE_VERIFIER_VERSION_MISMATCH"
    return VERIFIER_PATH, None


def verify_sigstore_bundle(
    root: Path,
    attestation_path: str | Path,
    bundle_path: str | Path,
    commit: str,
    source_ref: str,
) -> bool:
    executable, verifier_error = verifier_executable(root)
    try:
        trusted_root_digest = sha256_bytes((root / TRUSTED_ROOT_PATH).read_bytes())
    except OSError:
        return False
    if (
        verifier_error is not None
        or executable is None
        or re.fullmatch(r"[0-9a-f]{40}", commit) is None
        or not allowed_source_ref(source_ref)
        or trusted_root_digest != TRUSTED_ROOT_SHA256
    ):
        return False
    try:
        run = subprocess.run(
            sigstore_command(
                executable,
                str(attestation_path),
                str(bundle_path),
                commit,
                source_ref,
            ),
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )
        verified = json.loads(run.stdout) if run.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return False
    if not isinstance(verified, list) or len(verified) != 1:
        return False
    result = verified[0].get("verificationResult") if isinstance(verified[0], dict) else None
    return isinstance(result, dict) and bool(result.get("verifiedTimestamps"))


def sigstore_verified(
    root: Path,
    attestation_path: str,
    bundle_path: str,
    receipt: Mapping[str, Any],
    source_ref: object,
) -> bool:
    commit = receipt.get("commit_sha")
    return bool(
        isinstance(commit, str)
        and isinstance(source_ref, str)
        and verify_sigstore_bundle(root, attestation_path, bundle_path, commit, source_ref)
    )
