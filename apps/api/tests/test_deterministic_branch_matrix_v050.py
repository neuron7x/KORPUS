from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from korpus import config_policy
from korpus.application import assurance_calculus as ac
from korpus.application import deployment, retrieval
from korpus.application import release_ledger as ledger
from korpus.application.tenancy_ports import BillingEventIgnored
from korpus.config import Settings, _read_optional_secret_file, _read_secret_file
from korpus.domain.models import (
    AccessTier,
    Citation,
    DocumentCreate,
    EvidenceSpanRecord,
    Identity,
    QueryRequest,
    VersionCreate,
)
from korpus.infrastructure.liqpay import (
    LiqPayBillingProvider,
    _amount_minor,
    _mapped_status,
    _provider_datetime,
)
from korpus.security.browser_oidc import BrowserOIDCClient, BrowserSessionCodec, BrowserSessionError

SOURCE = "a" * 64
RELEASE = "v0.4.0"


def _cfg(**kw):
    base = dict(
        environment="test",
        runtime_role="api",
        auth_mode="oidc",
        dev_mode_acknowledgement="I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
        bind_host="127.0.0.1",
        browser_auth_enabled=False,
        browser_session_cookie="__Host-korpus_session",
        browser_csrf_cookie="__Host-korpus_csrf",
        browser_flow_cookie="__Secure-korpus_flow",
        browser_cookie_secure=False,
        oidc_authorization_endpoint="https://id.example/authorize",
        oidc_token_endpoint="https://id.example/token",
        oidc_client_id="client",
        oidc_redirect_uri="https://korpus.example/cb",
        resolved_browser_session_key="s" * 32,
        answer_composer_enabled=False,
        query_planner_enabled=False,
        semantic_retrieval_enabled=False,
        database_url="sqlite:///x.db",
        embedding_endpoint=None,
        embedding_model_id=None,
        semantic_weight=0.0,
        answer_policy_mode="development",
        resolved_embedding_token=None,
        audit_anchor_mode="file",
        audit_anchor_url=None,
        object_store_mode="local",
        s3_bucket=None,
        resolved_jwt_secret="j" * 40,
        chunk_overlap_chars=10,
        max_chunk_chars=100,
        entitlement_profile_path=None,
        entitlement_profile_sha256=None,
        source_trust_profile_path=None,
        source_trust_profile_sha256=None,
        require_source_signatures=False,
        reviewer_registry_path=None,
        reviewer_registry_sha256=None,
        corpus_governance_profile_path=None,
        corpus_governance_profile_sha256=None,
        calibration_profile_path=None,
        calibration_dataset_path=None,
        calibration_system_manifest_path=None,
        calibration_evaluation_protocol_path=None,
        calibration_profile_sha256=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_config_policy_auth_and_controlled_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="OIDC authentication"):
        config_policy._validate_auth(
            _cfg(environment="production", auth_mode="dev"), controlled=True
        )
    with pytest.raises(ValueError, match="acknowledgement"):
        config_policy._validate_auth(
            _cfg(auth_mode="dev", dev_mode_acknowledgement="no"), controlled=False
        )
    with pytest.raises(ValueError, match="loopback"):
        config_policy._validate_auth(_cfg(auth_mode="dev", bind_host="0.0.0.0"), controlled=False)
    config_policy._validate_auth(_cfg(auth_mode="dev"), controlled=False)
    with pytest.raises(ValueError, match="cannot disable"):
        config_policy._validate_auth(_cfg(auth_mode="disabled"), controlled=True)
    config_policy._validate_auth(_cfg(auth_mode="disabled"), controlled=False)

    config_policy._validate_controlled_requirements(_cfg(), controlled=False)
    monkeypatch.setattr(config_policy, "first_unmet", lambda settings: None)
    config_policy._validate_controlled_requirements(_cfg(), controlled=True)
    monkeypatch.setattr(
        config_policy, "first_unmet", lambda settings: SimpleNamespace(message="missing-X")
    )
    with pytest.raises(ValueError, match="missing-X"):
        config_policy._validate_controlled_requirements(_cfg(), controlled=True)


def test_config_policy_browser_model_semantic_and_runtime_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_policy._validate_browser_oidc(_cfg(browser_auth_enabled=False), controlled=False)
    with pytest.raises(ValueError, match="requires OIDC"):
        config_policy._validate_browser_oidc(
            _cfg(browser_auth_enabled=True, auth_mode="jwt"), controlled=False
        )
    with pytest.raises(ValueError, match="endpoints"):
        config_policy._validate_browser_oidc(
            _cfg(browser_auth_enabled=True, oidc_client_id=""), controlled=False
        )
    with pytest.raises(ValueError, match="32 characters"):
        config_policy._validate_browser_oidc(
            _cfg(browser_auth_enabled=True, resolved_browser_session_key="x"), controlled=False
        )
    with pytest.raises(ValueError, match="must use HTTPS"):
        config_policy._validate_browser_oidc(
            _cfg(browser_auth_enabled=True, oidc_token_endpoint="http://id/token"), controlled=False
        )
    with pytest.raises(ValueError, match="redirect URI"):
        config_policy._validate_browser_oidc(
            _cfg(browser_auth_enabled=True, oidc_redirect_uri="http://remote/cb"), controlled=False
        )
    config_policy._validate_browser_oidc(_cfg(browser_auth_enabled=True), controlled=False)

    monkeypatch.setattr(config_policy, "validate_model_provider", lambda settings: None)
    monkeypatch.setattr(config_policy, "resolved_model_api_key", lambda settings: None)
    with pytest.raises(ValueError, match="composer is enabled"):
        config_policy._validate_model_integrations(_cfg(answer_composer_enabled=True))
    monkeypatch.setattr(config_policy, "resolved_model_api_key", lambda settings: "key")
    with pytest.raises(ValueError, match="refused in a controlled"):
        config_policy._validate_model_integrations(
            _cfg(answer_composer_enabled=True, environment="controlled")
        )
    monkeypatch.setattr(config_policy, "resolved_model_api_key", lambda settings: None)
    with pytest.raises(ValueError, match="planner is enabled"):
        config_policy._validate_model_integrations(_cfg(query_planner_enabled=True))
    monkeypatch.setattr(config_policy, "resolved_model_api_key", lambda settings: "key")
    with pytest.raises(ValueError, match="refused in a isolated"):
        config_policy._validate_model_integrations(
            _cfg(query_planner_enabled=True, environment="isolated")
        )
    config_policy._validate_model_integrations(_cfg())

    with pytest.raises(ValueError, match="PostgreSQL"):
        config_policy._validate_semantic_retrieval(
            _cfg(semantic_retrieval_enabled=True), controlled=False
        )
    with pytest.raises(ValueError, match="endpoint and model"):
        config_policy._validate_semantic_retrieval(
            _cfg(semantic_retrieval_enabled=True, database_url="postgresql://db"), controlled=False
        )
    with pytest.raises(ValueError, match="positive semantic weight"):
        config_policy._validate_semantic_retrieval(
            _cfg(
                semantic_retrieval_enabled=True,
                database_url="postgresql://db",
                embedding_endpoint="https://e",
                embedding_model_id="m",
                semantic_weight=0,
            ),
            controlled=False,
        )
    with pytest.raises(ValueError, match="must use HTTPS"):
        config_policy._validate_semantic_retrieval(
            _cfg(
                semantic_retrieval_enabled=True,
                database_url="postgresql://db",
                embedding_endpoint="http://e",
                embedding_model_id="m",
                semantic_weight=0.1,
            ),
            controlled=True,
        )
    with pytest.raises(ValueError, match="requires authentication"):
        config_policy._validate_semantic_retrieval(
            _cfg(
                semantic_retrieval_enabled=True,
                database_url="postgresql://db",
                embedding_endpoint="https://e",
                embedding_model_id="m",
                semantic_weight=0.1,
            ),
            controlled=True,
        )
    with pytest.raises(ValueError, match="digest-bound corpus governance"):
        config_policy._validate_semantic_retrieval(
            _cfg(
                semantic_retrieval_enabled=True,
                database_url="postgresql://db",
                embedding_endpoint="https://e",
                embedding_model_id="m",
                semantic_weight=0.1,
                resolved_embedding_token="t",
            ),
            controlled=True,
        )
    config_policy._validate_semantic_retrieval(
        _cfg(
            semantic_retrieval_enabled=True,
            database_url="postgresql://db",
            embedding_endpoint="https://e",
            embedding_model_id="m",
            semantic_weight=0.1,
            resolved_embedding_token="t",
            corpus_governance_profile_path="governance.json",
            corpus_governance_profile_sha256="a" * 64,
        ),
        controlled=True,
    )
    with pytest.raises(ValueError, match="must be zero"):
        config_policy._validate_semantic_retrieval(_cfg(semantic_weight=0.1), controlled=False)
    config_policy._validate_semantic_retrieval(_cfg(), controlled=False)

    with pytest.raises(ValueError, match="audit_anchor_url"):
        config_policy._validate_runtime_integrations(
            _cfg(audit_anchor_mode="http"), controlled=False
        )
    with pytest.raises(ValueError, match="s3_bucket"):
        config_policy._validate_runtime_integrations(_cfg(object_store_mode="s3"), controlled=False)
    with pytest.raises(ValueError, match="durable remote object storage"):
        config_policy._validate_runtime_integrations(_cfg(), controlled=True)
    with pytest.raises(ValueError, match="JWT secret"):
        config_policy._validate_runtime_integrations(
            _cfg(auth_mode="jwt", resolved_jwt_secret="replace-me"), controlled=False
        )
    with pytest.raises(ValueError, match="overlap"):
        config_policy._validate_runtime_integrations(
            _cfg(chunk_overlap_chars=100), controlled=False
        )
    config_policy._validate_runtime_integrations(_cfg(), controlled=False)


def test_config_secret_and_enum_validator_matrix(tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.write_text("  abc  ", encoding="utf-8")
    assert _read_secret_file(secret, "fallback") == "abc"
    assert _read_optional_secret_file(None, "fallback") == "fallback"
    assert _read_optional_secret_file(secret, None) == "abc"
    empty = tmp_path / "empty"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty secret"):
        _read_secret_file(empty, "fallback")
    with pytest.raises(ValueError, match="empty secret"):
        _read_optional_secret_file(empty, None)

    validators = [
        (Settings.validate_audit_anchor_mode, "bad"),
        (Settings.validate_object_store_mode, "bad"),
        (Settings.validate_schema_mode, "bad"),
        (Settings.validate_auth_mode, "bad"),
        (Settings.validate_ingestion_mode, "bad"),
        (Settings.validate_malware_scan_mode, "bad"),
        (Settings.validate_policy_mode, "bad"),
    ]
    for validator, value in validators:
        with pytest.raises(ValueError):
            validator(value)
    assert Settings.validate_audit_anchor_mode("file") == "file"
    assert Settings.validate_object_store_mode("local") == "local"
    assert Settings.validate_schema_mode("auto") == "auto"
    assert Settings.validate_auth_mode("oidc") == "oidc"
    assert Settings.validate_ingestion_mode("synchronous") == "synchronous"
    assert Settings.validate_malware_scan_mode("disabled") == "disabled"
    assert Settings.validate_policy_mode("development") == "development"


def _ev(
    status: str = "PASS", cls: ac.EvidenceClass = ac.EvidenceClass.EXECUTED, **kw
) -> ac.EvidencePoint:
    executed = kw.pop("executed", cls >= ac.EvidenceClass.EXECUTED)
    negative = kw.pop("negative_control", cls >= ac.EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL)
    independent = kw.pop("independent", cls >= ac.EvidenceClass.INDEPENDENT_ATTESTED)
    attested = kw.pop("attested", cls >= ac.EvidenceClass.INDEPENDENT_ATTESTED)
    return ac.EvidencePoint(
        cls,
        kw.pop("source_digest", SOURCE),
        kw.pop("release", RELEASE),
        status,
        executed,
        negative,
        independent,
        attested,
    )


def test_assurance_validation_and_ceiling_matrix() -> None:
    with pytest.raises(ValueError, match="source_digest"):
        ac.EvidencePoint(ac.EvidenceClass.NONE, "z", RELEASE, "PASS")
    with pytest.raises(ValueError, match="status"):
        ac.EvidencePoint(ac.EvidenceClass.NONE, "", RELEASE, "MAYBE")
    with pytest.raises(ValueError, match="negative-control"):
        ac.EvidencePoint(
            ac.EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL, SOURCE, RELEASE, "PASS", True, False
        )
    with pytest.raises(ValueError, match="independent attested"):
        ac.EvidencePoint(
            ac.EvidenceClass.INDEPENDENT_ATTESTED, SOURCE, RELEASE, "PASS", True, True, False, True
        )
    for weight in (0.0, 1.1):
        with pytest.raises(ValueError, match="weight"):
            ac.DimensionPolicy("x", weight)
    with pytest.raises(ValueError, match="ceilings"):
        ac.DimensionPolicy("x", 1.0, -1, 90, 97)
    with pytest.raises(ValueError, match="monotone"):
        ac.DimensionPolicy("x", 1.0, 95, 90, 97)
    with pytest.raises(ValueError, match="score"):
        ac.DimensionObservation(101, _ev())
    with pytest.raises(ValueError, match="dimension ids"):
        ac.ReadinessPolicy((ac.DimensionPolicy("x", 0.5), ac.DimensionPolicy("x", 0.5)), ())
    with pytest.raises(ValueError, match="gate ids"):
        ac.ReadinessPolicy(
            (ac.DimensionPolicy("x", 1.0),), (ac.GateRequirement("g"), ac.GateRequirement("g"))
        )

    p = ac.DimensionPolicy("x", 1.0)
    assert (
        ac.evidence_ceiling(
            p, ac.EvidencePoint(ac.EvidenceClass.DECLARATIVE, SOURCE, RELEASE, "PASS")
        )
        == 70
    )
    assert ac.evidence_ceiling(p, _ev(cls=ac.EvidenceClass.EXECUTED)) == 90
    assert ac.evidence_ceiling(p, _ev(cls=ac.EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL)) == 97
    assert ac.evidence_ceiling(p, _ev(cls=ac.EvidenceClass.INDEPENDENT_ATTESTED)) == 100
    assert (
        ac.calibrated_dimension_score(
            p, ac.DimensionObservation(99, _ev("FAIL")), source_digest=SOURCE, release=RELEASE
        )
        == 0
    )


def test_assurance_gate_and_join_matrix() -> None:
    p = ac.ReadinessPolicy(
        (ac.DimensionPolicy("x", 1.0),),
        (
            ac.GateRequirement(
                "g",
                require_negative_control=True,
                require_independent=True,
                require_attestation=True,
            ),
        ),
    )
    ok, failures = ac.evaluate_gate(
        p.mandatory_gates[0], None, source_digest=SOURCE, release=RELEASE
    )
    assert not ok and failures == ("g.missing",)
    weak = _ev(cls=ac.EvidenceClass.EXECUTED, source_digest="b" * 64, release="v9")
    ok, failures = ac.evaluate_gate(
        p.mandatory_gates[0], weak, source_digest=SOURCE, release=RELEASE
    )
    assert not ok and len(failures) >= 4
    result = ac.evaluate_readiness(p, {}, {"g": weak}, source_digest=SOURCE, release=RELEASE)
    assert result.dimension_scores["x"] == 0 and not result.production_authorized
    assert ac.join_evidence(_ev("UNKNOWN"), _ev("UNKNOWN")).status == "UNKNOWN"
    assert ac.join_evidence(_ev("FAIL"), _ev("UNKNOWN")).status == "FAIL"


def _ledger_event(**changes) -> ledger.ReleaseLedgerEvent:
    base = dict(
        sequence=1,
        release_identity_digest=SOURCE,
        release=RELEASE,
        from_stage="DRAFT",
        to_stage="INTEGRATED",
        author_subject="author",
        verifier_subject=None,
        gate_set_sha256="b" * 64,
        timestamp="2026-08-15T12:00:00Z",
        previous_event_sha256="0" * 64,
        withdrawal_reason=None,
        event_sha256="",
    )
    base.update(changes)
    return ledger.ReleaseLedgerEvent(**base)


def test_release_ledger_validation_and_integrity_matrix() -> None:
    cases = [
        ({"sequence": 0}, "sequence"),
        ({"release_identity_digest": "x"}, "SHA-256"),
        ({"gate_set_sha256": "x"}, "SHA-256"),
        ({"previous_event_sha256": "x"}, "SHA-256"),
        ({"event_sha256": "x"}, "SHA-256"),
        ({"release": "0.4.0"}, "version tag"),
        ({"author_subject": "   "}, "author_subject"),
        ({"timestamp": "not-a-time"}, "timestamp"),
        ({"timestamp": "2026-08-15T12:00:00"}, "timezone"),
        ({"to_stage": "WITHDRAWN", "withdrawal_reason": ""}, "reason"),
    ]
    for changes, message in cases:
        with pytest.raises(ValueError, match=message):
            _ledger_event(**changes)

    first = _ledger_event().with_hash()
    no_hash = _ledger_event()
    # Existing unhashed event must commit its computed hash as the next previous link.
    SimpleNamespace(
        identity=SimpleNamespace(canonical_digest=SOURCE, release=RELEASE),
        stage=SimpleNamespace(name="DRAFT"),
        author_subject="author",
    )
    # Directly exercise integrity helpers with admissible-but-invalid chain shapes.
    bad_sequence = replace(first, sequence=2)
    failures, _ = ledger._event_integrity_failures(
        1,
        bad_sequence,
        previous_hash="f" * 64,
        previous_to="VERIFIED",
        previous_time=datetime(2026, 8, 15, 13, tzinfo=UTC),
    )
    assert {
        "event[1].sequence",
        "event[1].previous_hash",
        "event[1].hash",
        "event[1].stage_continuity",
        "event[1].timestamp_monotonicity",
    }.issubset(failures)
    jump = _ledger_event(from_stage="DRAFT", to_stage="VERIFIED").with_hash()
    failures, _ = ledger._event_integrity_failures(
        1, jump, previous_hash="0" * 64, previous_to=None, previous_time=None
    )
    assert "event[1].non_sequential_transition" in failures
    after_withdraw = _ledger_event(from_stage="WITHDRAWN", to_stage="INTEGRATED").with_hash()
    failures, _ = ledger._event_integrity_failures(
        1, after_withdraw, previous_hash="0" * 64, previous_to=None, previous_time=None
    )
    assert "event[1].transition_after_withdrawal" in failures
    assert ledger._identity_failures(1, first, identity="c" * 64, release="v9") == [
        "event[1].release_identity",
        "event[1].release",
    ]
    assert no_hash.computed_sha256


def _sealed(codec: BrowserSessionCodec, data: dict, kind: str = "session") -> str:
    body = json.dumps(data, separators=(",", ":")).encode()
    nonce = b"N" * 12
    ciphertext = AESGCM(codec._key).encrypt(nonce, body, kind.encode())
    return codec._encode(nonce + ciphertext)


def test_browser_session_fail_closed_matrix() -> None:
    codec = BrowserSessionCodec("s" * 32, clock=lambda: 1000)
    with pytest.raises(BrowserSessionError, match="truncated"):
        codec.open(codec._encode(b"tiny"), expected_kind="session")
    with pytest.raises(BrowserSessionError, match="type mismatch"):
        codec.open(
            _sealed(codec, {"v": 2, "kind": "session", "iat": 900, "exp": 1100, "payload": {}}),
            expected_kind="session",
        )
    with pytest.raises(BrowserSessionError, match="timestamps"):
        codec.open(
            _sealed(codec, {"v": 1, "kind": "session", "iat": "900", "exp": 1100, "payload": {}}),
            expected_kind="session",
        )
    for iat, exp in ((1031, 1100), (900, 1000)):
        with pytest.raises(BrowserSessionError, match="expired"):
            codec.open(
                _sealed(codec, {"v": 1, "kind": "session", "iat": iat, "exp": exp, "payload": {}}),
                expected_kind="session",
            )
    with pytest.raises(BrowserSessionError, match="payload"):
        codec.open(
            _sealed(codec, {"v": 1, "kind": "session", "iat": 900, "exp": 1100, "payload": []}),
            expected_kind="session",
        )
    assert codec.open(
        _sealed(codec, {"v": 1, "kind": "session", "iat": 900, "exp": 1100, "payload": {"x": 1}}),
        expected_kind="session",
    ) == {"x": 1}


class _TokenResponse:
    def __init__(self, payload, *, fail=False):
        self.payload = payload
        self.fail = fail

    def raise_for_status(self):
        if self.fail:
            raise httpx.HTTPError("fail")

    def json(self):
        return self.payload


class _OIDCTransport:
    def __init__(self, response):
        self.response = response
        self.posts = []
        self.closed = False

    def post(self, url, data=None, headers=None):
        self.posts.append((url, data, headers))
        return self.response

    def close(self):
        self.closed = True


def _oidc_client(response, **kw):
    return BrowserOIDCClient(
        authorization_endpoint="https://id/a",
        token_endpoint="https://id/t",
        client_id="c",
        redirect_uri="https://app/cb",
        scopes=["profile", "openid"],
        client=_OIDCTransport(response),
        **kw,
    )


def test_browser_oidc_constructor_and_exchange_matrix() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        BrowserOIDCClient(
            authorization_endpoint="http://id/a",
            token_endpoint="https://id/t",
            client_id="c",
            redirect_uri="x",
            scopes=[],
        )
    with pytest.raises(ValueError, match="client id"):
        BrowserOIDCClient(
            authorization_endpoint="https://id/a",
            token_endpoint="https://id/t",
            client_id="",
            redirect_uri="x",
            scopes=[],
        )
    client = _oidc_client(
        _TokenResponse({"access_token": "a", "id_token": "i", "expires_in": 300}),
        client_secret="secret",
    )
    with pytest.raises(BrowserSessionError, match="incomplete"):
        client.exchange("", "v")
    tokens = client.exchange("code", "verifier")
    assert tokens.expires_in == 300 and client.client.posts[-1][1]["client_secret"] == "secret"
    for payload, message in [
        ({"access_token": "a"}, "incomplete"),
        ({"access_token": "a", "id_token": "i", "expires_in": 59}, "lifetime"),
        ({"access_token": "a", "id_token": "i", "expires_in": "300"}, "lifetime"),
    ]:
        bad = _oidc_client(_TokenResponse(payload))
        with pytest.raises(BrowserSessionError, match=message):
            bad.exchange("c", "v")
    failed = _oidc_client(_TokenResponse({}, fail=True))
    with pytest.raises(BrowserSessionError, match="exchange failed"):
        failed.exchange("c", "v")


def test_deployment_patch_branch_matrix(tmp_path: Path) -> None:
    path = tmp_path / "multi.yaml"
    path.write_text(
        "---\nkind: ConfigMap\nmetadata: {name: a}\n---\n- not-a-document\n", encoding="utf-8"
    )
    assert len(deployment._load_documents(path)) == 1
    with pytest.raises(deployment.RenderError, match="malformed"):
        deployment._navigate({}, "bad")
    with pytest.raises(deployment.RenderError, match="does not resolve"):
        deployment._navigate({}, "/missing/x")
    doc = {"items": [{"x": 1}, {"x": 2}], "obj": {"a": 1}}
    assert deployment._navigate(doc, "/items/-")[1] == 2
    assert deployment._navigate(doc, "/items/0/x")[1] == "x"
    deployment._apply_json6902(
        doc,
        [
            {"op": "replace", "path": "/items/0", "value": {"x": 3}},
            {"op": "add", "path": "/items/1", "value": {"x": 4}},
            {"op": "remove", "path": "/items/0"},
            {"op": "add", "path": "/obj/b", "value": 2},
            {"op": "remove", "path": "/obj/a"},
        ],
    )
    with pytest.raises(deployment.RenderError, match="absent"):
        deployment._apply_json6902({}, [{"op": "replace", "path": "/x", "value": 1}])
    with pytest.raises(deployment.RenderError, match="unsupported"):
        deployment._apply_json6902({}, [{"op": "move", "path": "/x"}])
    base = {"x": [{"a": 1}, 2], "nested": {"a": 1}}
    deployment._strategic_merge(base, {"x": [{"b": 2}, 3, 4], "nested": {"b": 2}, "z": 1})
    assert base == {"x": [{"a": 1, "b": 2}, 3, 4], "nested": {"a": 1, "b": 2}, "z": 1}


def test_liqpay_fail_closed_and_conversion_matrix() -> None:
    for args in [("", "k"), ("p", "")]:
        with pytest.raises(ValueError, match="keys"):
            LiqPayBillingProvider(*args)
    with pytest.raises(ValueError, match="algorithm"):
        LiqPayBillingProvider("p", "k", signature_algorithm="md5")
    sha1 = LiqPayBillingProvider("p", "k", signature_algorithm="sha1")
    assert sha1.sign_data("x")
    p = LiqPayBillingProvider("p", "k")
    with pytest.raises(ValueError, match="unsigned"):
        p.verify_event(b"x", None)
    with pytest.raises(ValueError, match="ASCII"):
        p.verify_event(b"\xff", "x")
    with pytest.raises(ValueError, match="signature"):
        p.verify_event(b"e30=", "x")
    bad = base64.b64encode(b"not-json")
    with pytest.raises(ValueError, match="malformed"):
        p.verify_event(bad, p.sign_data(bad.decode()))
    arr = base64.b64encode(b"[]")
    with pytest.raises(ValueError, match="not an object"):
        p.verify_event(arr, p.sign_data(arr.decode()))
    wrong = base64.b64encode(json.dumps({"public_key": "other"}).encode())
    with pytest.raises(ValueError, match="another merchant"):
        p.verify_event(wrong, p.sign_data(wrong.decode()))
    good = base64.b64encode(
        json.dumps(
            {"public_key": "p", "action": "regular", "status": "success", "payment_id": 123}
        ).encode()
    )
    event = p.verify_event(good, p.sign_data(good.decode()))
    assert p.event_identity(event)[0].startswith("123:")
    with pytest.raises(ValueError, match="stable transaction"):
        p.event_identity({"action": "x", "status": "y"})
    with pytest.raises(BillingEventIgnored):
        p.subscription_view({"action": "regular", "status": "wait"})
    with pytest.raises(ValueError, match="order_id"):
        p.subscription_view({"action": "regular", "status": "success"})
    assert _mapped_status("regular", "unsubscribed") == "canceled"
    with pytest.raises(ValueError, match="unsupported"):
        _mapped_status("x", "success")
    assert (
        _amount_minor(None) is None and _amount_minor("") is None and _amount_minor("1.23") == 123
    )
    for value, message in [("bad", "numeric"), ("1.001", "sub-minor"), (0, "positive")]:
        with pytest.raises(ValueError, match=message):
            _amount_minor(value)
    assert _provider_datetime(None) is None
    assert _provider_datetime(1_700_000_000).tzinfo is UTC
    assert _provider_datetime(1_700_000_000_000).tzinfo is UTC
    assert _provider_datetime("2026-08-15T12:00:00").tzinfo is UTC
    assert _provider_datetime("2026-08-15T12:00:00Z").tzinfo is not None
    assert _provider_datetime("bad") is None and _provider_datetime(object()) is None


def test_models_validation_and_retrieval_parameter_matrix() -> None:
    assert AccessTier.parse(AccessTier.RESTRICTED) is AccessTier.RESTRICTED
    assert AccessTier.parse(2) is AccessTier.REVIEWED
    with pytest.raises(ValueError):
        Identity(subject="x\ny", corpora=frozenset({"public"}))
    with pytest.raises(ValueError, match="at least one corpus"):
        Identity(subject="x", corpora=frozenset())
    with pytest.raises(ValueError, match="compartment"):
        DocumentCreate(canonical_title="abc", issuer="ii", compartments=frozenset({"BAD SPACE"}))
    with pytest.raises(ValueError, match="effective_until"):
        VersionCreate(
            revision="1", effective_from=date(2026, 2, 1), effective_until=date(2026, 1, 1)
        )
    span_id = uuid4()
    version_id = uuid4()
    with pytest.raises(ValueError, match="text_hash"):
        EvidenceSpanRecord(version_id=version_id, ordinal=0, text="x", text_hash="a" * 64)
    span = EvidenceSpanRecord(version_id=version_id, ordinal=0, text="x")
    assert span.text_hash == hashlib.sha256(b"x").hexdigest()
    with pytest.raises(ValueError, match="NUL"):
        QueryRequest(text="abc\x00def")
    quote = "quoted"
    qh = hashlib.sha256(quote.encode()).hexdigest()
    base = dict(
        document_id=uuid4(),
        version_id=version_id,
        span_id=span_id,
        title="t",
        revision="1",
        quote=quote,
        quote_start=0,
        quote_end=len(quote),
        quote_hash=qh,
        source_hash="b" * 64,
    )
    with pytest.raises(ValueError, match="quote_end"):
        Citation(**{**base, "quote_start": 2, "quote_end": 2})
    with pytest.raises(ValueError, match="quote_hash"):
        Citation(**{**base, "quote_hash": "c" * 64})
    assert Citation(**base).quote == quote

    for k1, b in ((0.09, 0.5), (4.1, 0.5), (1.5, -0.1), (1.5, 1.1)):
        with pytest.raises(ValueError):
            retrieval.BM25Parameters(k1, b)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        retrieval.RetrievalWeights(
            lexical=1.1,
            semantic=0,
            query_coverage=0,
            character=0,
            authority=0,
            phrase=0,
            temporal=0,
        )
    with pytest.raises(ValueError, match="sum to 1"):
        retrieval.RetrievalWeights(
            lexical=0.1,
            semantic=0,
            query_coverage=0,
            character=0,
            authority=0,
            phrase=0,
            temporal=0,
        )
    assert retrieval.character_ngrams("") == frozenset()
    assert retrieval.character_ngrams("ab") == frozenset({"ab"})
    assert retrieval.jaccard(frozenset(), frozenset({"x"})) == 0
    assert retrieval.jaccard(frozenset({"x"}), frozenset({"x", "y"})) == 0.5
    assert retrieval._ukrainian_stem("test") == "test"
    assert retrieval._ukrainian_stem("машинами") != "машинами"


def test_retrieval_scoring_validation_and_edge_matrix() -> None:
    with pytest.raises(ValueError, match="equal length"):
        retrieval.score_candidates("q", ["a"], [True, False])
    with pytest.raises(ValueError, match="component arrays"):
        retrieval.score_candidates("query", ["text"], authority_scores=[])
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        retrieval.score_candidates("query", ["text"], authority_scores=[2])
    assert retrieval.score_candidates("the and", ["text"]) == []
    assert retrieval.score_candidates("query", []) == []
    scored = retrieval.score_candidates(
        "alpha beta",
        ["", "alpha beta", "gamma"],
        semantic_scores=[0, 0.5, 0],
        temporal_scores=[0, 0.5, 0],
    )
    assert [s.index for s in scored] == [1, 2]
    assert retrieval._temporal_relevance(date(2026, 1, 1), None, None) == 0
    assert retrieval._temporal_relevance(date(2026, 1, 1), date(2027, 1, 1), None) == 0
    assert retrieval._temporal_relevance(date(2026, 1, 1), date(2026, 1, 1), None) == 1
