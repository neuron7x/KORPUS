#!/usr/bin/env python3
"""Generate and verify SLSA v1.2 Build Provenance statements for KORPUS artifacts.

The statement uses the in-toto Statement v1 envelope and the SLSA provenance/v1
predicate. It intentionally does *not* claim a SLSA level: levels describe properties of
the build platform. A local workstation builder is recorded as local/unattested and a
production verifier may require an explicitly trusted builder id.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
BUILD_TYPE = "https://korpus.dev/buildtypes/canonical-release-zip/v1"
LOCAL_BUILDER = "korpus://builder/local-unattested"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")


def release_identity(root: Path) -> dict[str, str]:
    payload = json.loads((root / "apps/api/src/korpus/release.json").read_text(encoding="utf-8"))
    version = str(payload.get("version", ""))
    tag = str(payload.get("tag", ""))
    if not version or tag != f"v{version}":
        raise ValueError("invalid canonical release identity")
    return {str(k): str(v) for k, v in payload.items()}


def material(root: Path, relative: str) -> dict[str, object]:
    path = root / relative
    if not path.is_file():
        raise ValueError(f"required build material missing: {relative}")
    return {"uri": f"file:///{relative}", "digest": {"sha256": sha256(path)}}


def build_statement(
    root: Path,
    artifact: Path,
    *,
    builder_id: str,
    invocation_id: str,
    started_on: str,
    finished_on: str,
) -> dict[str, object]:
    identity = release_identity(root)
    source_manifest = root / "SOURCE_MANIFEST.json"
    required_materials = (
        "SOURCE_MANIFEST.json",
        "apps/api/src/korpus/release.json",
        "apps/api/requirements.runtime.lock",
        "apps/api/requirements.dev.lock",
        "apps/web/package-lock.json",
        "apps/api/Dockerfile",
        "apps/web/Dockerfile",
    )
    resolved = [material(root, relative) for relative in required_materials]
    byproducts = []
    for relative in (
        "source-sbom.cdx.json",
        "api-sbom.cdx.json",
        "web-sbom.cdx.json",
        "reports/CANONICAL_RELEASE_REPORT.json",
        "reports/DEPENDENCY_LOCK_REPORT.json",
    ):
        path = root / relative
        if path.is_file():
            byproducts.append({"uri": f"file:///{relative}", "digest": {"sha256": sha256(path)}})
    return {
        "_type": STATEMENT_TYPE,
        "subject": [
            {
                "name": artifact.name,
                "digest": {"sha256": sha256(artifact)},
            }
        ],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "buildDefinition": {
                "buildType": BUILD_TYPE,
                "externalParameters": {
                    "release": identity["tag"],
                    "artifactStem": identity["artifact_stem"],
                    "sourceManifestSha256": sha256(source_manifest),
                },
                "internalParameters": {
                    "builderTrustClass": (
                        "LOCAL_UNATTESTED"
                        if builder_id == LOCAL_BUILDER
                        else "EXTERNALLY_IDENTIFIED"
                    )
                },
                "resolvedDependencies": resolved,
            },
            "runDetails": {
                "builder": {"id": builder_id},
                "metadata": {
                    "invocationId": invocation_id,
                    "startedOn": started_on,
                    "finishedOn": finished_on,
                },
                "byproducts": byproducts,
            },
        },
    }


def _load_trusted_builders(path: Path | None) -> set[str]:
    if path is None or not path.is_file():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    builders = payload.get("trusted_builder_ids", []) if isinstance(payload, dict) else []
    return {str(item) for item in builders if isinstance(item, str) and item}


def _dependency_index(statement: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        dependencies = statement["predicate"]["buildDefinition"]["resolvedDependencies"]
    except (KeyError, TypeError):
        return result
    if not isinstance(dependencies, list):
        return result
    for item in dependencies:
        if not isinstance(item, dict):
            continue
        uri = item.get("uri")
        digest = item.get("digest")
        if (
            isinstance(uri, str)
            and isinstance(digest, dict)
            and isinstance(digest.get("sha256"), str)
        ):
            result[uri] = digest["sha256"]
    return result


def _subject_failures(artifact: Path, statement: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    subjects = statement.get("subject")
    if not isinstance(subjects, list) or len(subjects) != 1 or not isinstance(subjects[0], dict):
        return ["subject.cardinality"]
    subject = subjects[0]
    if subject.get("name") != artifact.name:
        failures.append("subject.name")
    digest = subject.get("digest")
    if not isinstance(digest, dict) or digest.get("sha256") != sha256(artifact):
        failures.append("subject.digest")
    return failures


def _predicate_parts(statement: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    predicate = statement.get("predicate")
    if not isinstance(predicate, dict):
        return {}, {}
    build = predicate.get("buildDefinition")
    run = predicate.get("runDetails")
    return (
        build if isinstance(build, dict) else {},
        run if isinstance(run, dict) else {},
    )


def _build_failures(root: Path, build: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if build.get("buildType") != BUILD_TYPE:
        failures.append("build.type")
    external = build.get("externalParameters")
    identity = release_identity(root)
    if not isinstance(external, dict) or external.get("release") != identity["tag"]:
        failures.append("build.release")
    expected_manifest = sha256(root / "SOURCE_MANIFEST.json")
    if not isinstance(external, dict) or external.get("sourceManifestSha256") != expected_manifest:
        failures.append("build.source_manifest")
    return failures


def _material_failures(root: Path, statement: dict[str, Any]) -> list[str]:
    dependencies = _dependency_index(statement)
    required = (
        "SOURCE_MANIFEST.json",
        "apps/api/src/korpus/release.json",
        "apps/api/requirements.runtime.lock",
        "apps/api/requirements.dev.lock",
        "apps/web/package-lock.json",
        "apps/api/Dockerfile",
        "apps/web/Dockerfile",
    )
    return [
        f"material:{relative}"
        for relative in required
        if dependencies.get(f"file:///{relative}") != sha256(root / relative)
    ]


def _builder_failures(
    run: dict[str, Any], trusted_builders: set[str], require_trusted_builder: bool
) -> tuple[list[str], str | None]:
    builder = run.get("builder")
    builder_id = builder.get("id") if isinstance(builder, dict) else None
    failures: list[str] = []
    if not isinstance(builder_id, str) or not builder_id:
        failures.append("builder.id")
        builder_id = None
    if require_trusted_builder and builder_id not in trusted_builders:
        failures.append("builder.trusted")
    return failures, builder_id


def _valid_timestamp(value: object) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _metadata_failures(run: dict[str, Any]) -> list[str]:
    metadata = run.get("metadata")
    if not isinstance(metadata, dict):
        return ["metadata.invocation_id", "metadata.startedOn", "metadata.finishedOn"]
    failures: list[str] = []
    if not metadata.get("invocationId"):
        failures.append("metadata.invocation_id")
    for field in ("startedOn", "finishedOn"):
        if not _valid_timestamp(metadata.get(field)):
            failures.append(f"metadata.{field}")
    return failures


def verify_statement(
    root: Path,
    artifact: Path,
    statement: dict[str, Any],
    *,
    trusted_builders: set[str],
    require_trusted_builder: bool,
) -> dict[str, object]:
    failures: list[str] = []
    if statement.get("_type") != STATEMENT_TYPE:
        failures.append("statement.type")
    if statement.get("predicateType") != PREDICATE_TYPE:
        failures.append("statement.predicate_type")
    failures.extend(_subject_failures(artifact, statement))
    build, run = _predicate_parts(statement)
    failures.extend(_build_failures(root, build))
    failures.extend(_material_failures(root, statement))
    builder_failures, builder_id = _builder_failures(run, trusted_builders, require_trusted_builder)
    failures.extend(builder_failures)
    failures.extend(_metadata_failures(run))

    return {
        "schema": "korpus.slsa-provenance-verification.v1",
        "status": "PASS" if not failures else "FAIL",
        "artifact": artifact.name,
        "artifact_sha256": sha256(artifact),
        "builder_id": builder_id,
        "builder_trusted": bool(builder_id in trusted_builders),
        "slsa_level_claimed": False,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate")
    generate.add_argument("--artifact", type=Path, required=True)
    generate.add_argument("--out", type=Path, required=True)
    generate.add_argument("--builder-id", default=LOCAL_BUILDER)
    generate.add_argument("--invocation-id", default="")
    generate.add_argument("--started-on")
    generate.add_argument("--finished-on")

    verify = sub.add_parser("verify")
    verify.add_argument("--artifact", type=Path, required=True)
    verify.add_argument("--statement", type=Path, required=True)
    verify.add_argument("--trusted-builders", type=Path)
    verify.add_argument("--require-trusted-builder", action="store_true")

    args = parser.parse_args()
    if args.command == "generate":
        if not args.artifact.is_file():
            raise SystemExit(f"artifact missing: {args.artifact}")
        now = utc()
        statement = build_statement(
            ROOT,
            args.artifact,
            builder_id=args.builder_id,
            invocation_id=args.invocation_id or str(uuid.uuid4()),
            started_on=args.started_on or now,
            finished_on=args.finished_on or now,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(statement, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {"status": "PASS", "out": str(args.out), "builder_id": args.builder_id}, indent=2
            )
        )
        return 0

    try:
        statement = json.loads(args.statement.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(
            json.dumps({"status": "FAIL", "failures": [f"statement unreadable: {error}"]}, indent=2)
        )
        return 1
    if not isinstance(statement, dict):
        print(json.dumps({"status": "FAIL", "failures": ["statement must be an object"]}, indent=2))
        return 1
    verdict = verify_statement(
        ROOT,
        args.artifact,
        statement,
        trusted_builders=_load_trusted_builders(args.trusted_builders),
        require_trusted_builder=args.require_trusted_builder,
    )
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
