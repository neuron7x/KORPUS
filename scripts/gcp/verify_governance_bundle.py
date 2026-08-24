#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from korpus.application.calibration import CalibrationProfile
from korpus.security.corpus_governance import CorpusGovernanceProfile
from korpus.security.entitlements import EntitlementProfile
from korpus.security.reviewers import ReviewerRegistry
from korpus.security.source_authenticity import SourceTrustProfile

FILES = (
    "entitlements.json",
    "source-trust.json",
    "reviewers.json",
    "corpus-governance.json",
    "calibration.json",
    "calibration-dataset.jsonl",
    "system-manifest.json",
    "evaluation-protocol.md",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_complete_bundle(directory: Path) -> None:
    missing = [name for name in FILES if not (directory / name).is_file()]
    if missing:
        raise ValueError(f"governance bundle missing files: {', '.join(missing)}")


def verify(directory: Path, *, oidc_issuer: str, oidc_audience: str) -> dict[str, object]:
    directory = directory.resolve()
    _require_complete_bundle(directory)

    hashes = {name: sha256(directory / name) for name in FILES}

    entitlements = EntitlementProfile.load(directory / "entitlements.json", hashes["entitlements.json"])
    if entitlements.issuer != oidc_issuer:
        raise ValueError("entitlement issuer does not match production OIDC issuer")
    if entitlements.audience != oidc_audience:
        raise ValueError("entitlement audience does not match production OIDC audience")
    active_entitlement_targets = int(bool(entitlements.default.roles)) + sum(
        bool(grant.roles) for grant in entitlements.subjects.values()
    ) + sum(bool(grant.roles) for grant in entitlements.groups.values())
    if active_entitlement_targets < 1:
        raise ValueError("production entitlement profile grants no application role")

    source_trust = SourceTrustProfile.load(directory / "source-trust.json", hashes["source-trust.json"])
    active_source_keys = sum(not key.revoked for key in source_trust.keys.values())
    if active_source_keys < 1:
        raise ValueError("production source-trust profile has no active signing key")

    reviewers = ReviewerRegistry.load(directory / "reviewers.json", hashes["reviewers.json"])
    active_reviewer_subjects = sum(
        any(not grant.revoked for grant in grants) for grants in reviewers.subjects.values()
    )
    if active_reviewer_subjects < 2:
        raise ValueError("review separation requires at least two active reviewer subjects")

    governance = CorpusGovernanceProfile.load(
        directory / "corpus-governance.json", hashes["corpus-governance.json"]
    )
    if not governance.corpora:
        raise ValueError("production corpus governance has no corpus")

    calibration = CalibrationProfile.load(directory / "calibration.json", hashes["calibration.json"])
    calibration.validate_artifact_bindings(
        dataset=directory / "calibration-dataset.jsonl",
        system_manifest=directory / "system-manifest.json",
        evaluation_protocol=directory / "evaluation-protocol.md",
    )
    if not calibration.deployment_valid:
        raise ValueError(
            "calibration does not satisfy ranking and selective-answering deployment predicates"
        )

    manifest = {
        "schema_version": "1.0",
        "files": hashes,
        "bindings": {
            "oidc_issuer": oidc_issuer,
            "oidc_audience": oidc_audience,
            "entitlement_profile_id": entitlements.profile_id,
            "source_trust_profile_id": source_trust.profile_id,
            "reviewer_registry_id": reviewers.registry_id,
            "corpus_governance_profile_id": governance.profile_id,
            "calibration_profile_id": calibration.profile_id,
        },
        "acceptance": {
            "active_entitlement_targets": active_entitlement_targets,
            "active_source_keys": active_source_keys,
            "active_reviewer_subjects": active_reviewer_subjects,
            "calibration_ranking_valid": calibration.ranking_valid,
            "calibration_selective_answering_valid": calibration.selective_answering_valid,
        },
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest["release_id"] = hashlib.sha256(canonical).hexdigest()
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--oidc-issuer", required=True)
    parser.add_argument("--oidc-audience", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.directory, oidc_issuer=args.oidc_issuer, oidc_audience=args.oidc_audience)
    except Exception as exc:
        print(json.dumps({"verdict": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1
    payload = {"verdict": "PASS", **result}
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
