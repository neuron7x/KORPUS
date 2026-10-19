#!/usr/bin/env python3
"""Import and verify one main-branch hosted release-claim artifact."""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import zipfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from korpus.application.github_assurance_receipts import (  # noqa: E402
    CANONICAL_REPOSITORY,
    identity_from_run,
)
from korpus.application.release_claim_hosted import (  # noqa: E402
    ARTIFACT_GROUP,
    SOURCE_REF,
    allowed_source_ref,
    hosted_paths,
)
from korpus.application.release_claim_sigstore import (  # noqa: E402
    verifier_executable,
    verify_sigstore_bundle,
)
from release_claim_import_contract import (  # noqa: E402
    ATTESTATION_NAME,
    BUNDLE_NAME,
    EXPECTED_FILES,
    RECEIPT_NAME,
)
from release_claim_import_contract import (  # noqa: E402
    validate_downloaded as _validate_downloaded,
)
from release_identity import release_tag  # noqa: E402
from source_digest import commits_with_identical_source  # noqa: E402

_IMPORT_ERRORS = (
    OSError,
    ValueError,
    json.JSONDecodeError,
    subprocess.CalledProcessError,
    subprocess.TimeoutExpired,
)


def _gh() -> str:
    executable, refusal = verifier_executable(ROOT)
    if executable is None or refusal is not None:
        raise ValueError(f"pinned GitHub verifier unavailable: {refusal}")
    return executable


def _gh_json(endpoint: str) -> dict[str, Any]:
    run = subprocess.run(
        [_gh(), "api", endpoint], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if run.returncode != 0:
        raise ValueError(f"gh api {endpoint}: {run.stderr.strip()[:200]}")
    value = json.loads(run.stdout)
    if not isinstance(value, dict):
        raise ValueError(f"gh api {endpoint}: response is not an object")
    return value


def _gh_bytes(endpoint: str) -> bytes:
    run = subprocess.run(
        [_gh(), "api", "--header", "Accept: application/vnd.github+json", endpoint],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if run.returncode != 0:
        detail = run.stderr.decode(errors="replace").strip()[:200]
        raise ValueError(f"gh api {endpoint}: {detail}")
    return run.stdout


def _run(repository: str, run_id: str) -> dict[str, Any]:
    initial = _gh_json(f"repos/{repository}/actions/runs/{run_id}")
    attempt = initial.get("run_attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise ValueError("GitHub run has no positive attempt")
    return _gh_json(f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}")


def _artifact(repository: str, run_id: str, started: str) -> dict[str, Any]:
    response = _gh_json(f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100")
    artifacts = response.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("GitHub artifacts response has no list")
    matches = [
        item
        for item in artifacts
        if isinstance(item, dict)
        and item.get("name") == ARTIFACT_GROUP
        and str(item.get("created_at", "")) >= started
        and item.get("expired") is not True
    ]
    if len(matches) != 1:
        raise ValueError(f"artifact {ARTIFACT_GROUP} has {len(matches)} current candidates")
    artifact_id = matches[0].get("id")
    if not isinstance(artifact_id, int) or isinstance(artifact_id, bool) or artifact_id < 1:
        raise ValueError("release-claim artifact has no positive numeric id")
    return matches[0]


def _download(repository: str, artifact_id: int) -> dict[str, bytes]:
    archive = _gh_bytes(f"repos/{repository}/actions/artifacts/{artifact_id}/zip")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            files: dict[str, bytes] = {}
            for item in bundle.infolist():
                if item.is_dir():
                    continue
                path = PurePosixPath(item.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("release-claim artifact contains an unsafe path")
                name = path.name
                if name in files:
                    raise ValueError(f"release-claim artifact duplicates basename {name}")
                files[name] = bundle.read(item)
    except zipfile.BadZipFile as error:
        raise ValueError("release-claim artifact is not a ZIP archive") from error
    if set(files) != EXPECTED_FILES:
        raise ValueError(
            f"release-claim artifact files are {sorted(files)}, expected {sorted(EXPECTED_FILES)}"
        )
    return files


def _verify_sigstore(
    root: Path, attestation: Path, bundle: Path, commit: str, source_ref: str
) -> None:
    if not verify_sigstore_bundle(root, attestation, bundle, commit, source_ref):
        raise ValueError("GitHub Sigstore verification failed")


def validate_downloaded(
    root: Path,
    identity: Mapping[str, Any],
    artifact_id: int,
    files: Mapping[str, bytes],
    *,
    source_ref: str,
    verifier: Any = _verify_sigstore,
) -> dict[str, Any]:
    value = _validate_downloaded(root, identity, artifact_id, files, source_ref, verifier)
    return {str(key): item for key, item in value.items()}


def _write(root: Path, files: Mapping[str, bytes], admission: Mapping[str, Any]) -> list[str]:
    release = release_tag(root)
    attestation, receipt, admission_path, bundle = hosted_paths(release)
    destinations = {
        attestation: files[ATTESTATION_NAME],
        receipt: files[RECEIPT_NAME],
        bundle: files[BUNDLE_NAME],
        admission_path: (json.dumps(admission, ensure_ascii=False, indent=2) + "\n").encode(),
    }
    for relative, payload in destinations.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
        temporary.write_bytes(payload)
        os.replace(temporary, target)
    return sorted(destinations)


def _run_admissible(run: Mapping[str, Any], identity: Mapping[str, Any], source_ref: str) -> bool:
    event = run.get("event")
    allowed_event = (event == "push" and source_ref == SOURCE_REF) or (
        event == "workflow_dispatch" and source_ref != SOURCE_REF and allowed_source_ref(source_ref)
    )
    return bool(
        run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and allowed_event
        and identity.get("commit_sha") in frozenset(commits_with_identical_source())
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--repo", default=CANONICAL_REPOSITORY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.repo != CANONICAL_REPOSITORY:
            raise ValueError("foreign repository is not admissible")
        run = _run(args.repo, args.run)
        identity = identity_from_run(run)
        head_branch = run.get("head_branch")
        source_ref = f"refs/heads/{head_branch}" if isinstance(head_branch, str) else ""
        if not _run_admissible(run, identity, source_ref):
            raise ValueError("run is not an allowed successful source-identical workflow run")
        artifact = _artifact(args.repo, args.run, str(run.get("run_started_at", "")))
        artifact_id = int(artifact["id"])
        files = _download(args.repo, artifact_id)
        admission = validate_downloaded(ROOT, identity, artifact_id, files, source_ref=source_ref)
        written = [] if args.dry_run else _write(ROOT, files, admission)
    except _IMPORT_ERRORS as error:
        print(
            json.dumps(
                {
                    "schema": "korpus.release-claim-import.v1",
                    "status": "FAIL",
                    "reason": str(error),
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "schema": "korpus.release-claim-import.v1",
                "status": "PASS",
                "run_id": identity["run_id"],
                "run_attempt": identity["run_attempt"],
                "source_ref": source_ref,
                "written": written,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
