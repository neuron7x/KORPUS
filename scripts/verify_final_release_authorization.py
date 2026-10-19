#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from final_release_context import (  # noqa: E402
    configure_parser,
    release_build_context,
    trusted_builder_ids,
)
from korpus.application.assurance_trust import trusted_fingerprints  # noqa: E402
from korpus.application.final_release_authorization import evaluate_final_release  # noqa: E402
from korpus.application.final_release_evidence import (  # noqa: E402
    failed_candidate_verdict as failure,
)
from release_identity import release_tag  # noqa: E402

TRUST = ROOT / "config/assurance/trusted-assurance-signers.json"
BUILDERS = ROOT / "config/assurance/trusted-builders.v1.json"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _authorize(args: argparse.Namespace) -> dict[str, Any]:
    files = (
        args.artifact,
        args.release_manifest,
        args.release_attestation,
        args.builder_provenance,
        args.builder_attestation,
        args.production_assurance,
        args.source_manifest,
    )
    missing = [str(path) for path in files if not path.is_file()]
    if missing:
        return failure("missing:" + ",".join(missing))
    release = release_tag()
    build_context = release_build_context(ROOT, release)
    verdict = evaluate_final_release(
        artifact_name=args.artifact.name,
        artifact_bytes=args.artifact.read_bytes(),
        source_manifest_bytes=args.source_manifest.read_bytes(),
        production_assurance_bytes=args.production_assurance.read_bytes(),
        release_manifest_name=args.release_manifest.name,
        release_manifest_bytes=args.release_manifest.read_bytes(),
        release_attestation=_json(args.release_attestation),
        builder_statement_name=args.builder_provenance.name,
        builder_statement_bytes=args.builder_provenance.read_bytes(),
        builder_attestation=_json(args.builder_attestation),
        build_context=build_context,
        trusted_release_signers=trusted_fingerprints(
            TRUST, "release_ed25519_public_key_sha256", "KORPUS_TRUSTED_RELEASE_SIGNER_SHA256"
        ),
        trusted_builder_signers=trusted_fingerprints(
            TRUST,
            "hosted_builder_ed25519_public_key_sha256",
            "KORPUS_TRUSTED_HOSTED_BUILDER_SIGNER_SHA256",
        ),
        trusted_builder_ids=trusted_builder_ids(BUILDERS),
    )
    payload = verdict.as_dict()
    payload.update(
        release=release,
        source_commit=build_context.source_commit_sha,
        github_run_id=build_context.github_run_id,
        github_run_attempt=build_context.github_run_attempt,
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    configure_parser(parser, ROOT)
    args = parser.parse_args()
    try:
        payload = _authorize(args)
    except (OSError, ValueError) as error:
        payload = failure(f"verification_context:{error}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("production_authorized") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
