#!/usr/bin/env python3
"""Import exact SBOM/coverage artifacts from one canonical GitHub Actions attempt."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from korpus.application.coverage_evidence import (  # noqa: E402
    coverage_plan_problem,
    coverage_union_problem,
)
from korpus.application.github_assurance_receipts import (  # noqa: E402
    CANONICAL_REPOSITORY,
    admission_payload,
    canonical_identity,
    identity_from_run,
    receipt_bound,
    same_identity,
    sha256_bytes,
)
from korpus.application.sbom_evidence import (  # noqa: E402
    SbomCiEvidence,
    sbom_ci_receipts_bound,
    sbom_has_components,
    source_sbom_covers_lock,
)
from source_digest import commits_with_identical_source, source_tree_digest  # noqa: E402

OUT = ROOT / "var/ci-evidence"
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\\\s]+)")
ARTIFACTS = {
    "source-sbom": frozenset({"source-sbom.cdx.json", "source-sbom-receipt.json"}),
    "container-sboms": frozenset(
        {"api-sbom.cdx.json", "web-sbom.cdx.json", "container-sbom-receipt.json"}
    ),
    "coverage-union-evidence": frozenset(
        {"coverage-union.json", "coverage-gap-plan.json", "coverage-ci-receipt.json"}
    ),
}


def _gh_json(endpoint: str) -> dict[str, Any]:
    result = subprocess.run(
        ["gh", "api", endpoint], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise ValueError(f"gh api {endpoint}: {result.stderr.strip()[:200]}")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError(f"gh api {endpoint}: response is not an object")
    return value


def _gh_bytes(endpoint: str) -> bytes:
    result = subprocess.run(
        ["gh", "api", "--header", "Accept: application/vnd.github+json", endpoint],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode(errors="replace").strip()[:200]
        raise ValueError(f"gh api {endpoint}: {detail}")
    return result.stdout


def _run(repository: str, run_id: str) -> dict[str, Any]:
    value = _gh_json(f"repos/{repository}/actions/runs/{run_id}")
    attempt = value.get("run_attempt")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise ValueError("GitHub run has no positive attempt")
    return _gh_json(f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}")


def _artifacts(repository: str, run_id: str) -> list[dict[str, Any]]:
    value = _gh_json(f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("GitHub artifacts response has no list")
    return [item for item in artifacts if isinstance(item, dict)]


def _selected_artifacts(
    artifacts: list[dict[str, Any]], run_started_at: str
) -> dict[str, dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for name in ARTIFACTS:
        matches = [
            item
            for item in artifacts
            if item.get("name") == name
            and str(item.get("created_at", "")) >= run_started_at
            and item.get("expired") is not True
        ]
        if len(matches) != 1:
            raise ValueError(f"artifact {name} has {len(matches)} current-attempt candidates")
        artifact_id = matches[0].get("id")
        if not isinstance(artifact_id, int) or isinstance(artifact_id, bool):
            raise ValueError(f"artifact {name} has no numeric id")
        selected[name] = matches[0]
    return selected


def _download_group(
    repository: str, artifact_id: int, expected: frozenset[str]
) -> dict[str, bytes]:
    archive = _gh_bytes(f"repos/{repository}/actions/artifacts/{artifact_id}/zip")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            files: dict[str, bytes] = {}
            for path in bundle.namelist():
                if path.endswith("/"):
                    continue
                name = Path(path).name
                if name in files:
                    raise ValueError(f"artifact contains duplicate basename: {name}")
                files[name] = bundle.read(path)
    except zipfile.BadZipFile as error:
        raise ValueError("artifact is not a ZIP archive") from error
    if set(files) != expected:
        raise ValueError(f"artifact file set is {sorted(files)}, expected {sorted(expected)}")
    return files


def _json_bytes(payload: bytes, name: str) -> dict[str, Any]:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError(f"{name} is not a JSON object")
    return value


def _locks(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if match := PIN.match(line.strip()):
            result[match.group(1).lower().replace("_", "-")] = match.group(2)
    return result


def _admission_groups(groups: Mapping[str, tuple[int, Mapping[str, bytes]]]) -> dict[str, Any]:
    return {
        name: {
            "artifact_id": artifact_id,
            "files": {
                file_name: {"sha256": sha256_bytes(payload), "bytes": len(payload)}
                for file_name, payload in files.items()
            },
        }
        for name, (artifact_id, files) in groups.items()
    }


def validate_downloaded(
    identity: Mapping[str, Any],
    groups: Mapping[str, tuple[int, Mapping[str, bytes]]],
    source: str,
) -> dict[str, Any]:
    if not canonical_identity(identity) or set(groups) != set(ARTIFACTS):
        raise ValueError("run identity or imported artifact set is non-canonical")
    admission = admission_payload(identity, _admission_groups(groups))
    source_files = groups["source-sbom"][1]
    container_files = groups["container-sboms"][1]
    coverage_files = groups["coverage-union-evidence"][1]
    source_sbom = _json_bytes(source_files["source-sbom.cdx.json"], "source SBOM")
    api_sbom = _json_bytes(container_files["api-sbom.cdx.json"], "API SBOM")
    web_sbom = _json_bytes(container_files["web-sbom.cdx.json"], "web SBOM")
    source_receipt = _json_bytes(source_files["source-sbom-receipt.json"], "source receipt")
    container_receipt = _json_bytes(
        container_files["container-sbom-receipt.json"], "container receipt"
    )
    all_locks = {
        **_locks(ROOT / "apps/api/requirements.runtime.lock"),
        **_locks(ROOT / "apps/api/requirements.dev.lock"),
    }
    runtime = _locks(ROOT / "apps/api/requirements.runtime.lock")
    if (
        not source_sbom_covers_lock(source_sbom, all_locks)
        or not source_sbom_covers_lock(api_sbom, runtime)
        or not sbom_has_components(web_sbom, {"nginx"})
        or not sbom_ci_receipts_bound(
            SbomCiEvidence(
                source_sbom=source_sbom,
                api_sbom=api_sbom,
                web_sbom=web_sbom,
                api_locked=runtime,
                source_receipt=source_receipt,
                source_receipt_bytes=source_files["source-sbom-receipt.json"],
                container_receipt=container_receipt,
                container_receipt_bytes=container_files["container-sbom-receipt.json"],
                admission=admission,
                source_tree_sha256=source,
            ),
            source_sbom=source_files["source-sbom.cdx.json"],
            api_sbom=container_files["api-sbom.cdx.json"],
            web_sbom=container_files["web-sbom.cdx.json"],
        )
    ):
        raise ValueError("SBOM payload, completeness, subject, receipt, or admission mismatch")
    _validate_coverage(identity, admission, coverage_files, source)
    return admission


def _validate_coverage(
    identity: Mapping[str, Any],
    admission: Mapping[str, Any],
    files: Mapping[str, bytes],
    source: str,
) -> None:
    union = _json_bytes(files["coverage-union.json"], "coverage union")
    plan = _json_bytes(files["coverage-gap-plan.json"], "coverage plan")
    receipt = _json_bytes(files["coverage-ci-receipt.json"], "coverage receipt")
    union_meta = union.get("dialect_union")
    run = union_meta.get("github_run") if isinstance(union_meta, Mapping) else None
    if (
        coverage_union_problem(union) is not None
        or not receipt_bound(
            receipt,
            identity=identity,
            kind="coverage-union",
            job="coverage-union",
            source_tree_sha256=source,
            artifacts={
                "coverage-union.json": files["coverage-union.json"],
                "coverage-gap-plan.json": files["coverage-gap-plan.json"],
            },
        )
        or not isinstance(run, Mapping)
        or not same_identity(run, identity)
        or coverage_plan_problem(
            plan, union, hashlib.sha256(files["coverage-union.json"]).hexdigest()
        )
        is not None
        or not isinstance(plan.get("github_run"), Mapping)
        or not same_identity(plan["github_run"], identity)
        or not all(_admitted(admission, name, payload) for name, payload in files.items())
    ):
        raise ValueError("coverage union, plan, receipt, or admission mismatch")


def _admitted(admission: Mapping[str, Any], name: str, payload: bytes) -> bool:
    group = admission.get("artifacts", {}).get("coverage-union-evidence", {})
    record = group.get("files", {}).get(name, {}) if isinstance(group, Mapping) else {}
    return (
        isinstance(record, Mapping)
        and record.get("sha256") == sha256_bytes(payload)
        and record.get("bytes") == len(payload)
    )


def _success(identity: Mapping[str, Any], groups: Mapping[str, Any], written: bool) -> None:
    result = {
        "schema": "korpus.github-assurance-import.v1",
        "status": "PASS",
        "run_id": identity["run_id"],
        "run_attempt": identity["run_attempt"],
        "files": sorted(name for _, files in groups.values() for name in files),
        "written": written,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--repo", default=CANONICAL_REPOSITORY)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        if args.repo != CANONICAL_REPOSITORY:
            raise ValueError("foreign repository is not admissible")
        run = _run(args.repo, args.run)
        identity = identity_from_run(run)
        accepted = frozenset(commits_with_identical_source())
        if (
            run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or identity.get("commit_sha") not in accepted
        ):
            raise ValueError("run is incomplete, failed, or not source-identical to HEAD")
        selected = _selected_artifacts(
            _artifacts(args.repo, args.run), str(run.get("run_started_at", ""))
        )
        groups = {
            name: (
                int(selected[name]["id"]),
                _download_group(args.repo, int(selected[name]["id"]), expected),
            )
            for name, expected in ARTIFACTS.items()
        }
        admission = validate_downloaded(identity, groups, source_tree_digest("HEAD"))
        if not args.dry_run:
            args.out.mkdir(parents=True, exist_ok=True)
            for _, files in groups.values():
                for name, payload in files.items():
                    (args.out / name).write_bytes(payload)
            (args.out / "assurance-admission.json").write_text(
                json.dumps(admission, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {
                    "schema": "korpus.github-assurance-import.v1",
                    "status": "FAIL",
                    "reason": str(error),
                }
            )
        )
        return 1
    _success(identity, groups, not args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
