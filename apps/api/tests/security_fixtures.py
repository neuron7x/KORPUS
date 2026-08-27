from __future__ import annotations

import hashlib
from pathlib import Path

from korpus.domain.models import AccessTier
from korpus.security.entitlements import EntitlementGrant, EntitlementProfile


def write_entitlement_profile(tmp_path: Path) -> tuple[Path, str]:
    profile = EntitlementProfile(
        profile_id="test-entitlements-v1",
        issuer="https://id.example",
        audience="korpus-api",
        default=EntitlementGrant(roles=frozenset({"user"}), corpora=frozenset({"public"})),
        groups={
            "korpus-admins": EntitlementGrant(
                roles=frozenset({"admin", "curator", "reviewer", "auditor", "user"}),
                clearance=AccessTier.RESTRICTED,
                corpora=frozenset({"public", "training", "restricted-demo"}),
                compartments=frozenset({"operations"}),
            )
        },
    )
    path = tmp_path / "entitlements.json"
    raw = profile.model_dump_json().encode("utf-8")
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def write_source_trust_profile(tmp_path: Path) -> tuple[Path, str]:
    import base64

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from korpus.domain.models import AuthorityClass
    from korpus.security.source_authenticity import SourceTrustKey, SourceTrustProfile

    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    profile = SourceTrustProfile(
        profile_id="test-source-trust-v1",
        keys={
            "test-official-key": SourceTrustKey(
                key_id="test-official-key",
                issuer="Test Issuer",
                public_key_b64=base64.b64encode(public_raw).decode("ascii"),
                authorities=frozenset({AuthorityClass.OFFICIAL_UA}),
            )
        },
    )
    path = tmp_path / "source-trust.json"
    raw = profile.model_dump_json().encode("utf-8")
    path.write_bytes(raw)
    # Private key is returned indirectly for tests only, never written by production helpers.
    write_source_trust_profile.last_private_key = private
    return path, hashlib.sha256(raw).hexdigest()


def write_reviewer_registry(tmp_path: Path) -> tuple[Path, str]:
    from korpus.domain.models import AuthorityClass, ReviewState
    from korpus.security.reviewers import ReviewerGrant, ReviewerRegistry

    grant = ReviewerGrant(
        credential_id="test-reviewer-credential",
        stages=frozenset(
            {
                ReviewState.METADATA_REVIEWED,
                ReviewState.CONTENT_REVIEWED,
                ReviewState.APPROVED,
            }
        ),
        corpora=frozenset({"public", "training", "restricted-demo"}),
        authorities=frozenset(
            {
                AuthorityClass.OFFICIAL_UA,
                AuthorityClass.OFFICIAL_ALLIED,
                AuthorityClass.APPROVED_TRAINING,
            }
        ),
    )
    profile = ReviewerRegistry(
        registry_id="test-reviewers-v1",
        subjects={
            "admin-test": (grant,),
            "metadata-reviewer": (
                grant.model_copy(update={"credential_id": "metadata-credential"}),
            ),
            "content-reviewer": (grant.model_copy(update={"credential_id": "content-credential"}),),
            "approver-test": (grant.model_copy(update={"credential_id": "approver-credential"}),),
        },
    )
    path = tmp_path / "reviewers.json"
    raw = profile.model_dump_json().encode("utf-8")
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def write_corpus_governance_profile(tmp_path: Path) -> tuple[Path, str]:
    from korpus.domain.models import AuthorityClass, Classification
    from korpus.security.corpus_governance import (
        CorpusGovernanceProfile,
        CorpusOperation,
        CorpusPolicy,
    )

    common = CorpusPolicy(
        data_owner="Test Data Owner",
        security_owner="Test Security Owner",
        rights_reference="TEST-RIGHTS-001",
        releasability="test-only",
        allowed_classifications=frozenset(
            {Classification.PUBLIC, Classification.INTERNAL, Classification.RESTRICTED}
        ),
        allowed_authorities=frozenset(
            {
                AuthorityClass.OFFICIAL_UA,
                AuthorityClass.OFFICIAL_ALLIED,
                AuthorityClass.APPROVED_TRAINING,
            }
        ),
        allowed_operations=frozenset(
            {
                CorpusOperation.INDEX,
                CorpusOperation.OCR,
                CorpusOperation.CITE,
                CorpusOperation.EXTERNAL_EMBEDDING,
                CorpusOperation.EXPORT,
                CorpusOperation.DELETE,
            }
        ),
        retention_days=365,
    )
    profile = CorpusGovernanceProfile(
        profile_id="test-corpus-governance-v1",
        corpora={
            "public": common,
            "training": common,
            "restricted-demo": common.model_copy(
                update={
                    "allowed_operations": frozenset(
                        {CorpusOperation.INDEX, CorpusOperation.OCR, CorpusOperation.CITE}
                    )
                }
            ),
        },
    )
    path = tmp_path / "corpus-governance.json"
    raw = profile.model_dump_json().encode("utf-8")
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def controlled_security_kwargs(tmp_path: Path) -> dict[str, object]:
    path, digest = write_entitlement_profile(tmp_path)
    source_path, source_digest = write_source_trust_profile(tmp_path)
    reviewer_path, reviewer_digest = write_reviewer_registry(tmp_path)
    governance_path, governance_digest = write_corpus_governance_profile(tmp_path)
    return {
        "entitlement_profile_path": path,
        "entitlement_profile_sha256": digest,
        "source_trust_profile_path": source_path,
        "source_trust_profile_sha256": source_digest,
        "require_source_signatures": True,
        "reviewer_registry_path": reviewer_path,
        "reviewer_registry_sha256": reviewer_digest,
        "corpus_governance_profile_path": governance_path,
        "corpus_governance_profile_sha256": governance_digest,
        "malware_scan_mode": "clamd",
        "parser_sandbox_enabled": True,
        "ingestion_mode": "durable_async",
        "browser_auth_enabled": True,
        "browser_session_key": "controlled-browser-session-key-for-tests-0000000000",
        "browser_cookie_secure": True,
        "oidc_authorization_endpoint": "https://id.example/authorize",
        "oidc_token_endpoint": "https://id.example/token",
        "oidc_client_id": "korpus-browser",
        "oidc_redirect_uri": "https://korpus.example/v1/auth/callback",
    }


def write_calibration_bundle(tmp_path: Path, **profile_overrides: object) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    from korpus.application.calibration import CalibrationProfile

    dataset = tmp_path / "calibration-dataset.jsonl"
    system_manifest = tmp_path / "system-manifest.json"
    protocol = tmp_path / "evaluation-protocol.md"
    dataset.write_text('{"id":"calibration-case","query":"test"}\n', encoding="utf-8")
    system_manifest.write_text('{"schema":1,"source":"test-fixture"}\n', encoding="utf-8")
    protocol.write_text(
        "# Frozen evaluation protocol\n\nNo post-hoc threshold edits.\n", encoding="utf-8"
    )
    values: dict[str, object] = {
        "profile_id": "calibration-test-v3",
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "system_manifest_sha256": hashlib.sha256(system_manifest.read_bytes()).hexdigest(),
        "evaluation_protocol_sha256": hashlib.sha256(protocol.read_bytes()).hexdigest(),
        "accepted_samples": 2000,
        "observed_errors": 10,
        "confidence_delta": 0.05,
        "risk_limit": 0.05,
        "minimum_score": 0.4,
        "minimum_query_coverage": 0.5,
        "minimum_support_score": 0.35,
        "minimum_calibration_samples": 200,
        "ranking_evaluated_queries": 500,
        "ndcg_at_10": 0.82,
        "mrr_at_10": 0.86,
        "recall_at_20": 0.94,
    }
    values.update(profile_overrides)
    profile = CalibrationProfile(**values)
    profile_path = tmp_path / "calibration.json"
    profile_path.write_text(profile.model_dump_json(), encoding="utf-8")
    return {
        "calibration_profile_path": profile_path,
        "calibration_profile_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        "calibration_dataset_path": dataset,
        "calibration_system_manifest_path": system_manifest,
        "calibration_evaluation_protocol_path": protocol,
    }
