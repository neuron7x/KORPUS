#!/usr/bin/env python3
"""Build subject-to-artifact receipts inside the canonical assurance workflow."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from korpus.application.coverage_evidence import (  # noqa: E402
    coverage_plan_problem,
    coverage_union_problem,
)
from korpus.application.github_assurance_receipts import (  # noqa: E402
    identity_from_environment,
    new_receipt,
    same_identity,
    sha256_bytes,
)
from korpus.application.sbom_evidence import (  # noqa: E402
    sbom_has_components,
    source_sbom_covers_lock,
    valid_cyclonedx,
)
from source_digest import source_tree_digest  # noqa: E402

PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\\\s]+)")


def _bytes(path: Path) -> bytes:
    if not path.is_file():
        raise ValueError(f"missing evidence input: {path}")
    return path.read_bytes()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(_bytes(path))
    if not isinstance(value, dict):
        raise ValueError(f"evidence input is not an object: {path}")
    return value


def _locked(paths: tuple[Path, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if match := PIN.match(line.strip()):
                result[match.group(1).lower().replace("_", "-")] = match.group(2)
    return result


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, indent=2))


def source_receipt(args: argparse.Namespace) -> dict[str, Any]:
    payload = _bytes(args.sbom)
    sbom = _json(args.sbom)
    locks = _locked(
        (ROOT / "apps/api/requirements.runtime.lock", ROOT / "apps/api/requirements.dev.lock")
    )
    if not source_sbom_covers_lock(sbom, locks):
        raise ValueError("source SBOM is invalid or incomplete for locked dependencies")
    source = source_tree_digest("HEAD")
    return new_receipt(
        identity_from_environment(),
        kind="source-sbom",
        job="source-sbom",
        source_tree_sha256=source,
        artifacts={args.sbom.name: payload},
        subjects={
            "source-tree": {
                "digest_scope": "tracked_tree",
                "sha256": source,
                "sbom": args.sbom.name,
                "sbom_sha256": sha256_bytes(payload),
                "expected_locked_components": len(locks),
            }
        },
    )


def container_receipt(args: argparse.Namespace) -> dict[str, Any]:
    api_sbom, web_sbom = _json(args.api_sbom), _json(args.web_sbom)
    runtime = _locked((ROOT / "apps/api/requirements.runtime.lock",))
    if not source_sbom_covers_lock(api_sbom, runtime):
        raise ValueError("API image SBOM is incomplete for the runtime lock")
    if not valid_cyclonedx(web_sbom) or not sbom_has_components(web_sbom, {"nginx"}):
        raise ValueError("web image SBOM is invalid or does not contain nginx")
    api_image, web_image = _bytes(args.api_image), _bytes(args.web_image)
    artifacts = {
        args.api_sbom.name: _bytes(args.api_sbom),
        args.web_sbom.name: _bytes(args.web_sbom),
    }
    return new_receipt(
        identity_from_environment(),
        kind="container-sboms",
        job="container-sbom",
        source_tree_sha256=source_tree_digest("HEAD"),
        artifacts=artifacts,
        subjects={
            args.api_image.name: {
                "sha256": sha256_bytes(api_image),
                "sbom": args.api_sbom.name,
                "sbom_sha256": sha256_bytes(artifacts[args.api_sbom.name]),
                "expected_runtime_components": len(runtime),
            },
            args.web_image.name: {
                "sha256": sha256_bytes(web_image),
                "sbom": args.web_sbom.name,
                "sbom_sha256": sha256_bytes(artifacts[args.web_sbom.name]),
                "expected_components": ["nginx"],
            },
        },
    )


def coverage_receipt(args: argparse.Namespace) -> dict[str, Any]:
    union_bytes, plan_bytes = _bytes(args.union), _bytes(args.plan)
    union, plan = _json(args.union), _json(args.plan)
    identity = identity_from_environment()
    if problem := coverage_union_problem(union):
        raise ValueError(problem)
    if problem := coverage_plan_problem(plan, union, sha256_bytes(union_bytes)):
        raise ValueError(f"coverage plan is not bound to the exact union: {problem}")
    if not same_identity(union["dialect_union"].get("github_run", {}), identity):
        raise ValueError("coverage union is not bound to this workflow attempt")
    source = source_tree_digest("HEAD")
    subject = union["korpus_coverage"]
    if subject.get("source_tree_sha256") != source:
        raise ValueError("coverage union describes another source tree")
    artifacts = {args.union.name: union_bytes, args.plan.name: plan_bytes}
    return new_receipt(
        identity,
        kind="coverage-union",
        job="coverage-union",
        source_tree_sha256=source,
        artifacts=artifacts,
        subjects={
            "dialect-coverage": {
                "union": args.union.name,
                "union_sha256": sha256_bytes(union_bytes),
                "plan": args.plan.name,
                "plan_sha256": sha256_bytes(plan_bytes),
                "source_inputs_sha256": subject["source_inputs_sha256"],
                "input_sha256": union["dialect_union"]["input_sha256"],
                "input_receipt_sha256": union["dialect_union"]["input_receipt_sha256"],
            }
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    source = commands.add_parser("source-sbom")
    source.add_argument("--sbom", type=Path, required=True)
    source.add_argument("--out", type=Path, required=True)
    containers = commands.add_parser("container-sboms")
    containers.add_argument("--api-image", type=Path, required=True)
    containers.add_argument("--web-image", type=Path, required=True)
    containers.add_argument("--api-sbom", type=Path, required=True)
    containers.add_argument("--web-sbom", type=Path, required=True)
    containers.add_argument("--out", type=Path, required=True)
    coverage = commands.add_parser("coverage-union")
    coverage.add_argument("--union", type=Path, required=True)
    coverage.add_argument("--plan", type=Path, required=True)
    coverage.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    builders = {
        "source-sbom": source_receipt,
        "container-sboms": container_receipt,
        "coverage-union": coverage_receipt,
    }
    try:
        receipt = builders[args.command](args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAIL", "reason": str(error)}))
        return 1
    _write(args.out, receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
