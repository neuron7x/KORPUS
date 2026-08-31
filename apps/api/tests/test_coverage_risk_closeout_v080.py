from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from korpus.api.billing_dependencies import _state
from korpus.application.assurance_trust import trusted_fingerprints
from korpus.application.attested_evidence import verify_ed25519_attestation
from korpus.application.composition import CompositionRefused, admissible_opening
from korpus.application.egress import EgressDenied, EgressPosture, ModelEgressPolicy
from korpus.application.extraction_quality import assess_extraction_quality
from korpus.application.provenance import _digest_candidates
from korpus.application.recovery import INCOMPLETE_PROVENANCE, classify_recovery
from korpus.application.supply_chain_scanners import scanner_summary_clean
from korpus.application.trace import set_trace_id
from korpus.config import Settings
from korpus.domain.tenancy import AccountRecord
from korpus.infrastructure.audit_event_view import _iso
from korpus.infrastructure.deterministic_billing import _timestamp
from korpus.security.source_authenticity import SourceTrustProfile
from starlette.applications import Starlette
from starlette.requests import Request


def test_missing_trust_config_is_an_empty_trust_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KORPUS_TEST_TRUST_ROOT", raising=False)
    assert (
        trusted_fingerprints(tmp_path / "missing.json", "keys", "KORPUS_TEST_TRUST_ROOT") == set()
    )


def test_non_ed25519_key_never_verifies_an_ed25519_attestation() -> None:
    public = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    pem = public.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    verdict = verify_ed25519_attestation(
        b"manifest",
        manifest_name="manifest.json",
        release="v0.8.0",
        attestation={"public_key_pem": pem.decode("ascii"), "signature_base64": ""},
        trusted_fingerprints=(),
    )
    assert verdict.checks["signature"] is False


def test_malformed_scanner_record_container_fails_closed() -> None:
    assert scanner_summary_clean({"status": "PASS", "worst_exit_code": 0, "scanners": {}}) is False


def test_source_trust_profile_digest_mismatch_fails_before_parse(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        SourceTrustProfile.load(path, "0" * 64)


def test_invalid_trace_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid trace id"):
        set_trace_id("line\nbreak")


def test_low_alphanumeric_density_is_explicitly_flagged() -> None:
    result = assess_extraction_quality("!" * 20)
    assert "low_alphanumeric_density" in result.flags


def test_oidc_scope_list_restores_required_openid_scope() -> None:
    assert Settings(oidc_scopes="profile email").oidc_scope_list[0] == "openid"


def test_tenant_auth_subject_rejects_control_whitespace() -> None:
    with pytest.raises(ValueError, match="control characters"):
        AccountRecord(auth_subject="subject\nadmin")


def test_empty_composer_opening_is_refused() -> None:
    with pytest.raises(CompositionRefused, match="empty opening"):
        admissible_opening("   ", ["evidence"])


def test_local_only_egress_requires_a_hostname() -> None:
    with pytest.raises(EgressDenied, match="endpoint carries no host"):
        ModelEgressPolicy(EgressPosture.LOCAL_ONLY).check("http:///path-only")


def test_recovery_report_without_provenance_is_incomplete() -> None:
    verdict = classify_recovery({"status": "PASS"})
    assert verdict.status == INCOMPLETE_PROVENANCE


def test_non_string_billing_timestamp_is_not_coerced() -> None:
    assert _timestamp(None) is None


def test_naive_audit_datetime_is_normalized_to_utc() -> None:
    assert _iso(datetime(2026, 1, 1)).endswith("+00:00")


def test_missing_billing_runtime_dependency_returns_503() -> None:
    app = Starlette()
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "app": app})
    with pytest.raises(HTTPException) as exc:
        _state(request, "subscription_store")
    assert exc.value.status_code == 503


def test_provenance_ignores_compiled_python_suffixes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "kept.py").write_text("x = 1\n", encoding="utf-8")
    (source / "ignored.pyc").write_bytes(b"compiled")
    candidates = _digest_candidates(tmp_path, ("source",))
    assert [path.name for path in candidates] == ["kept.py"]


def test_account_enable_requires_a_nonblank_reason() -> None:
    from uuid import uuid4

    from korpus.application.accounts import AccountService
    from korpus.domain.models import Identity

    service = AccountService(object())  # branch rejects before store access
    with pytest.raises(ValueError, match="requires a reason"):
        service.enable(Identity(subject="actor"), uuid4(), "   ")


def test_aware_audit_datetime_preserves_timezone_without_replacement() -> None:
    from datetime import UTC

    assert _iso(datetime(2026, 1, 1, tzinfo=UTC)).endswith("+00:00")


def test_unsellable_liqpay_plan_is_rejected_before_checkout_generation() -> None:
    from korpus.domain.tenancy import AccountRecord, PlanRecord, SubscriptionRecord
    from korpus.infrastructure.liqpay import LiqPayBillingProvider

    account = AccountRecord(auth_subject="subject")
    plan = PlanRecord(code="free", name="Free")
    subscription = SubscriptionRecord(account_id=account.id, plan_id=plan.id, provider="liqpay")
    provider = LiqPayBillingProvider("public", "private")
    with pytest.raises(ValueError, match="plan is not sellable"):
        provider.create_checkout(
            account=account,
            subscription=subscription,
            plan=plan,
            callback_url="https://example.invalid/callback",
            result_url="https://example.invalid/result",
        )


def test_oidc_browser_mode_without_cookie_reaches_authentication_required_branch() -> None:
    from korpus.security.auth import get_identity

    settings = Settings(
        auth_mode="oidc",
        browser_auth_enabled=True,
        oidc_authorization_endpoint="https://idp.example/authorize",
        oidc_token_endpoint="https://idp.example/token",
        oidc_client_id="client",
        oidc_redirect_uri="http://127.0.0.1/callback",
        browser_session_key="x" * 32,
    )
    app = Starlette()
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "app": app})
    with pytest.raises(HTTPException) as exc:
        get_identity(None, settings, request)
    assert exc.value.status_code == 401


def test_valid_version_ingestion_job_takes_version_target_branch() -> None:
    from uuid import uuid4

    from korpus.domain.models import Identity, IngestionJobKind, IngestionJobRecord, VersionCreate

    job = IngestionJobRecord(
        kind=IngestionJobKind.VERSION,
        actor=Identity(subject="actor"),
        document_id=uuid4(),
        version=VersionCreate(revision="1"),
        filename="document.txt",
        mime_type="text/plain",
        source_hash="0" * 64,
        staging_object_key="staging/object",
    )
    assert job.kind is IngestionJobKind.VERSION
