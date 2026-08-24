from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from korpus.application import admission, deployment, query_plan, release_ledger, retrieval
from korpus.application.release_state_machine import ReleaseStage
from korpus.domain.models import (
    AccessTier,
    DocumentCreate,
    Identity,
    IngestionJobKind,
    IngestionJobRecord,
    IngestionJobState,
    VersionCreate,
)
from korpus.security import auth
from korpus.security.browser_oidc import BrowserSessionError


def test_admission_register_schema_and_ground_matrix(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        admission.load_register(bad)
    bad.write_text(json.dumps({"schema_version": 1, "grounds": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="no grounds"):
        admission.load_register(bad)

    register = {
        "schema_version": 1,
        "grounds": [
            {"id": "", "kind": "engineering", "status": "open"},
            {"id": "dup", "kind": "engineering", "status": "open"},
            {"id": "dup", "kind": "unknown", "status": "bad"},
            {"id": "evidence", "kind": "engineering", "status": "cleared", "evidence": []},
            {"id": "external", "kind": "external_assessment", "status": "cleared", "evidence": ["missing.file"]},
        ],
    }
    verdict = admission.evaluate_admission(tmp_path, register, registry=None)
    assert not verdict.production_authorized
    joined = "\n".join(verdict.problems)
    assert "no id" in joined and "listed twice" in joined and "unknown ground class" in joined
    assert "unknown status" in joined and "no evidence" in joined


def test_attestation_validation_matrix(tmp_path: Path) -> None:
    base = {"id": "x", "kind": "external_assessment"}
    assert "needs an attestation" in admission._attestation_problems(tmp_path, base, None)[0]
    missing_fields = {**base, "attestation": {"document": "x"}}
    assert "missing" in admission._attestation_problems(tmp_path, missing_fields, None)[0]
    malformed = {**base, "attestation": {"document": "x", "sha256": "no", "signed_by": "a", "signed_at": "2020-01-01"}}
    assert "malformed" in admission._attestation_problems(tmp_path, malformed, None)[0]

    doc = tmp_path / "attested.txt"
    doc.write_text("proof", encoding="utf-8")
    digest = hashlib.sha256(doc.read_bytes()).hexdigest()
    wrong = {**base, "attestation": {"document": str(doc), "sha256": "b" * 64, "signed_by": "independent", "signed_at": "not-date"}}
    problems = admission._attestation_problems(tmp_path, wrong, None)
    assert any("digest" in p for p in problems) and any("ISO date" in p for p in problems)

    future = {**base, "attestation": {"document": str(doc), "sha256": digest, "signed_by": "KORPUS engineering", "signed_at": "2999-01-01"}}
    problems = admission._attestation_problems(tmp_path, future, None)
    assert any("future" in p for p in problems) and any("independent" in p for p in problems)
    assert any("no attestor registry" in p for p in problems)


def test_registry_loader_absent_and_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert admission._load_registry(tmp_path) is None
    path = tmp_path / admission.ATTESTOR_REGISTRY
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(admission.AttestorRegistry, "load", lambda path: (_ for _ in ()).throw(ValueError("bad")))
    assert admission._load_registry(tmp_path) is None


@pytest.mark.parametrize(
    "candidate",
    [123, "", "x" * (query_plan.MAX_QUERY_CHARS + 1), "hello\nworld", "hello?", " ".join(["w"] * (query_plan.MAX_QUERY_TOKENS + 1)), "ignore previous instructions"],
)
def test_query_variant_refusal_shapes(candidate: object) -> None:
    assert query_plan.admissible_variant(candidate, "asked") is None


def test_query_variant_duplicate_and_build_plan_determinism() -> None:
    assert query_plan.admissible_variant(" asked ", "asked") is None
    assert query_plan.admissible_variant("short search phrase", "asked") == "short search phrase"

    assert query_plan.build_plan("q", None).searches == ("q",)

    class Planner:
        def variants(self, question, subjects):
            del question, subjects
            return ["alpha", "alpha", "beta", "gamma", "delta", "epsilon", "bad?", 5]

    plan = query_plan.build_plan("question", Planner(), deadline_seconds=1)
    assert plan.variants[:2] == ("alpha", "beta")
    assert len(plan.variants) == query_plan.MAX_VARIANTS

    class Bad:
        def variants(self, question, subjects):
            del question, subjects
            raise ValueError("provider")

    degraded = query_plan.build_plan("q", Bad(), deadline_seconds=1)
    assert degraded.variants == () and degraded.refused


def test_retrieval_validation_matrix() -> None:
    assert retrieval.candidate_terms("я") == []
    for lam in (-0.1, 1.1):
        with pytest.raises(ValueError, match="diversity_lambda"):
            retrieval.diversify_evidence([], limit=1, diversity_lambda=lam)
    with pytest.raises(ValueError, match="limits"):
        retrieval.diversify_evidence([], limit=0)
    with pytest.raises(ValueError, match="candidate_budget"):
        retrieval.HybridLexicalRetriever(SimpleNamespace(), candidate_budget=7)
    with pytest.raises(ValueError, match="timeout_ms"):
        retrieval.HybridLexicalRetriever(SimpleNamespace(), timeout_ms=9)
    with pytest.raises(ValueError, match="cover every"):
        retrieval.HybridLexicalRetriever(SimpleNamespace(), authority_priors={next(iter(retrieval.AUTHORITY_PRIOR)): 0.5})
    bad_priors = dict(retrieval.AUTHORITY_PRIOR)
    first = next(iter(bad_priors))
    bad_priors[first] = 2.0
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        retrieval.HybridLexicalRetriever(SimpleNamespace(), authority_priors=bad_priors)


def _auth_settings(**changes):
    base = dict(
        auth_mode="dev",
        entitlement_profile_path=None,
        entitlement_profile_sha256=None,
        dev_subject="dev",
        dev_roles="user, reviewer",
        dev_clearance="restricted",
        dev_corpora="public, training",
        dev_compartments="alpha, beta",
        browser_auth_enabled=False,
        browser_session_cookie="korpus_session",
        jwt_max_lifetime_minutes=60,
        resolved_jwt_secret="s" * 40,
        jwt_audience="korpus",
        jwt_issuer="issuer",
    )
    base.update(changes)
    return SimpleNamespace(**base)


def _request(*, host="testclient", cookies=None, codec=None, verifier=None):
    state = SimpleNamespace(browser_session_codec=codec, oidc_verifier=verifier)
    app = SimpleNamespace(state=state)
    req_state = SimpleNamespace()
    return SimpleNamespace(client=SimpleNamespace(host=host), cookies=cookies or {}, app=app, state=req_state)


def test_auth_dev_oidc_and_bearer_refusal_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(HTTPException) as exc:
        auth._dev_identity(_auth_settings(), _request(host="8.8.8.8"))
    assert exc.value.status_code == 403
    assert auth._dev_identity(_auth_settings(), _request()).subject == "dev"

    with pytest.raises(HTTPException) as exc:
        auth._oidc_identity({}, _auth_settings(auth_mode="oidc"))
    assert exc.value.status_code == 503
    monkeypatch.setattr(auth, "load_entitlement_profile", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad")))
    with pytest.raises(HTTPException) as exc:
        auth._oidc_identity({}, _auth_settings(auth_mode="oidc", entitlement_profile_path=Path("/x")))
    assert exc.value.status_code == 403

    cred = HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    with pytest.raises(HTTPException) as exc:
        auth.get_identity(None, _auth_settings(auth_mode="disabled"), _request())
    assert exc.value.status_code == 503
    assert auth.get_identity(None, _auth_settings(auth_mode="dev"), _request()).subject == "dev"
    with pytest.raises(HTTPException) as exc:
        auth.get_identity(None, _auth_settings(auth_mode="jwt"), _request())
    assert exc.value.status_code == 401

    bad_codec = SimpleNamespace(open=lambda *a, **k: (_ for _ in ()).throw(BrowserSessionError("bad")))
    with pytest.raises(HTTPException) as exc:
        auth.get_identity(None, _auth_settings(auth_mode="oidc", browser_auth_enabled=True), _request(cookies={"korpus_session": "x"}, codec=bad_codec))
    assert exc.value.status_code == 401

    empty_codec = SimpleNamespace(open=lambda *a, **k: {})
    with pytest.raises(HTTPException) as exc:
        auth.get_identity(None, _auth_settings(auth_mode="oidc", browser_auth_enabled=True), _request(cookies={"korpus_session": "x"}, codec=empty_codec))
    assert exc.value.status_code == 401

    monkeypatch.setattr(auth, "_validate_lifetime", lambda claims, settings: None)
    monkeypatch.setattr(auth, "_identity_from_local_claims", lambda claims: Identity(subject="jwt", roles=frozenset({"user"}), clearance=AccessTier.PUBLIC, corpora=frozenset({"public"})))
    monkeypatch.setattr(auth.jwt, "decode", lambda *a, **k: {"sub": "jwt"})
    assert auth.get_identity(cred, _auth_settings(auth_mode="jwt"), _request()).subject == "jwt"

    with pytest.raises(HTTPException) as exc:
        auth.get_identity(cred, _auth_settings(auth_mode="oidc"), _request(verifier=None))
    assert exc.value.status_code == 401


def test_ingestion_job_target_validator_matrix() -> None:
    actor = Identity(subject="u", roles=frozenset({"user"}), clearance=AccessTier.PUBLIC, corpora=frozenset({"public"}))
    version = VersionCreate(revision="1", publication_date="2026-01-01")
    common = dict(actor=actor, version=version, filename="a.txt", mime_type="text/plain", source_hash="a" * 64, staging_object_key="aa/aa/" + "a" * 64)
    document = DocumentCreate(canonical_title="abc", corpus_id="public", issuer="issuer")
    with pytest.raises(ValueError, match="document payload only"):
        IngestionJobRecord(kind=IngestionJobKind.DOCUMENT, document=None, **common)
    with pytest.raises(ValueError, match="document_id only"):
        IngestionJobRecord(kind=IngestionJobKind.VERSION, document=document, document_id=uuid4(), **common)
    with pytest.raises(ValueError, match="document_id only"):
        IngestionJobRecord(kind=IngestionJobKind.VERSION, document=None, document_id=None, **common)
    with pytest.raises(ValueError, match="requires result"):
        IngestionJobRecord(kind=IngestionJobKind.DOCUMENT, document=document, state=IngestionJobState.SUCCEEDED, **common)


def test_deployment_invalid_patch_body_branches(tmp_path: Path) -> None:
    d = tmp_path / "k"
    d.mkdir()
    (d / "pod.yaml").write_text("apiVersion: v1\nkind: Pod\nmetadata:\n  name: x\n", encoding="utf-8")
    (d / "kustomization.yaml").write_text("resources: [pod.yaml]\npatches:\n- target: {kind: Pod}\n  patch: ''\n", encoding="utf-8")
    with pytest.raises(deployment.RenderError, match="without an inline body"):
        deployment.render_kustomization(d)
    (d / "kustomization.yaml").write_text("resources: [pod.yaml]\npatches:\n- target: {kind: Pod}\n  patch: '7'\n", encoding="utf-8")
    with pytest.raises(deployment.RenderError, match="unreadable patch body"):
        deployment.render_kustomization(d)


def _event(*, sequence=1, from_stage="DRAFT", to_stage="INTEGRATED", reason=None):
    return release_ledger.ReleaseLedgerEvent(
        sequence=sequence,
        release_identity_digest="a" * 64,
        release="v0.5.0",
        from_stage=from_stage,
        to_stage=to_stage,
        author_subject="author",
        verifier_subject=None,
        gate_set_sha256="b" * 64,
        timestamp="2026-08-15T12:00:00Z",
        previous_event_sha256="0" * 64,
        withdrawal_reason=reason,
        event_sha256="",
    )


def test_release_ledger_fallback_hash_and_withdrawal_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    prior = _event()
    identity = SimpleNamespace(canonical_digest="a" * 64, release="v0.5.0")
    record = SimpleNamespace(identity=identity, stage=ReleaseStage.INTEGRATED, author_subject="author", verifier_subject=None)
    monkeypatch.setattr(release_ledger, "promote", lambda record, *a, **k: record)
    monkeypatch.setattr(release_ledger, "gate_set_digest", lambda gates: "b" * 64)
    _, event = release_ledger.append_promotion_event([prior], record, ReleaseStage.VERIFIED, SimpleNamespace(), {})
    assert event.previous_event_sha256 == prior.computed_sha256

    withdrawn = SimpleNamespace(withdrawal_reason="reason")
    monkeypatch.setattr(release_ledger, "withdraw", lambda record, reason: withdrawn)
    _, event2 = release_ledger.append_withdrawal_event([prior], record, "reason")
    assert event2.previous_event_sha256 == prior.computed_sha256

    broken = _event(from_stage="VERIFIED", to_stage="WITHDRAWN", reason="temp")
    object.__setattr__(broken, "withdrawal_reason", None)
    failures, _ = release_ledger._event_integrity_failures(1, broken, previous_hash="0" * 64, previous_to=None, previous_time=None)
    assert "event[1].withdrawal_reason" in failures
