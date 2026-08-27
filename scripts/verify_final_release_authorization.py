#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]

from korpus.application.assurance_trust import trusted_fingerprints  # noqa: E402
from korpus.application.final_release_authorization import evaluate_final_release  # noqa: E402
from release_identity import release_tag  # noqa: E402

TRUST = ROOT / "config/assurance/trusted-assurance-signers.json"
BUILDERS = ROOT / "config/assurance/trusted-builders.v1.json"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _builder_ids() -> set[str]:
    payload = _json(BUILDERS)
    result = {
        str(item)
        for item in payload.get("trusted_builder_ids", ())
        if isinstance(item, str) and item
    }
    if os.getenv("KORPUS_TRUSTED_BUILDER_ID"):
        result.add(str(os.environ["KORPUS_TRUSTED_BUILDER_ID"]))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--release-attestation", type=Path, required=True)
    parser.add_argument("--builder-provenance", type=Path, required=True)
    parser.add_argument("--builder-attestation", type=Path, required=True)
    parser.add_argument(
        "--production-assurance",
        type=Path,
        default=ROOT / "reports/PRODUCTION_ASSURANCE_REPORT.json",
    )
    parser.add_argument("--source-manifest", type=Path, default=ROOT / "SOURCE_MANIFEST.json")
    parser.add_argument("--out", type=Path, default=ROOT / "var/production/final_release-gate.json")
    args = parser.parse_args()
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
        payload = {
            "schema": "korpus.final-production-authorization.v1",
            "status": "FAIL",
            "production_authorized": False,
            "checks": {},
            "failures": [f"missing:{item}" for item in missing],
        }
    else:
        release = release_tag()
        verdict = evaluate_final_release(
            artifact_name=args.artifact.name,
            artifact_bytes=args.artifact.read_bytes(),
            source_manifest_bytes=args.source_manifest.read_bytes(),
            production_assurance_bytes=args.production_assurance.read_bytes(),
            production_assurance=_json(args.production_assurance),
            release_manifest_name=args.release_manifest.name,
            release_manifest_bytes=args.release_manifest.read_bytes(),
            release_manifest=_json(args.release_manifest),
            release_attestation=_json(args.release_attestation),
            builder_statement_name=args.builder_provenance.name,
            builder_statement_bytes=args.builder_provenance.read_bytes(),
            builder_statement=_json(args.builder_provenance),
            builder_attestation=_json(args.builder_attestation),
            release=release,
            trusted_release_signers=trusted_fingerprints(
                TRUST, "release_ed25519_public_key_sha256", "KORPUS_TRUSTED_RELEASE_SIGNER_SHA256"
            ),
            trusted_builder_signers=trusted_fingerprints(
                TRUST,
                "hosted_builder_ed25519_public_key_sha256",
                "KORPUS_TRUSTED_HOSTED_BUILDER_SIGNER_SHA256",
            ),
            trusted_builder_ids=_builder_ids(),
        )
        payload = verdict.as_dict()
        payload["release"] = release
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("production_authorized") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
