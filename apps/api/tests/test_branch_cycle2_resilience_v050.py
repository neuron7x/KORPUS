from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest

from korpus.application.ingestion import ExtractionSettings, IngestionService
from korpus.application.policy import PolicyEngine
from korpus.domain.models import AccessTier, AuthorityClass, Identity, ReviewState, ReviewTransition, VersionCreate
from korpus.infrastructure import audit_anchor
from korpus.security.oidc import OIDCVerifier


def test_anchor_codec_file_monotonic_cleanup_and_reset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    codec = audit_anchor._SignedAnchorCodec(b"k" * 32)
    with pytest.raises(audit_anchor.AnchorError, match="invalid fields"):
        codec.encode(-1, "0" * 64)
    with pytest.raises(audit_anchor.AnchorError, match="unreadable"):
        codec.decode({"schema": 2, "sequence": 0, "head_hash": "0" * 64, "mac": "x"})
    bad = codec.encode(0, "0" * 64)
    bad["head_hash"] = "short"
    with pytest.raises(audit_anchor.AnchorError, match="invalid fields"):
        codec.decode(bad)

    path = tmp_path / "anchor.json"
    store = audit_anchor.FileAuditAnchorStore(path, b"k" * 32)
    store.write(2, "2" * 64)
    store.write(1, "1" * 64)  # monotonic no-op
    assert store.read().sequence == 2
    with pytest.raises(audit_anchor.AnchorError, match="conflicting"):
        store.write(2, "3" * 64)
    store.reset()
    assert not path.exists()

    # Atomic failure must remove a temporary file rather than leave ambiguous state.
    real_replace = audit_anchor.os.replace
    monkeypatch.setattr(audit_anchor.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("replace")))
    with pytest.raises(OSError):
        store.write(3, "3" * 64)
    assert not list(tmp_path.glob(".audit-anchor-*"))
    monkeypatch.setattr(audit_anchor.os, "replace", real_replace)


class Resp:
    def __init__(self, code: int, payload=None, *, json_exc: Exception | None = None):
        self.status_code = code
        self.payload = payload
        self.json_exc = json_exc
    def json(self):
        if self.json_exc: raise self.json_exc
        return self.payload
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(str(self.status_code))


class HttpClient:
    def __init__(self):
        self.get_resp = Resp(404)
        self.put_resp = Resp(204)
        self.closed = False
    def get(self, endpoint): del endpoint; return self.get_resp
    def put(self, endpoint, **kwargs): del endpoint, kwargs; return self.put_resp
    def close(self): self.closed = True


def test_http_anchor_error_read_404_and_close_matrix() -> None:
    client = HttpClient()
    store = audit_anchor.HttpAuditAnchorStore("https://a.example", b"k" * 32, client=client)
    assert store.read().sequence == 0
    client.put_resp = Resp(500)
    with pytest.raises(audit_anchor.AnchorError, match="500"):
        store.write(1, "1" * 64)
    client.get_resp = Resp(200, json_exc=ValueError("bad"))
    with pytest.raises(audit_anchor.AnchorError, match="invalid JSON"):
        store.read()
    store.close()
    assert client.closed
    audit_anchor.HttpAuditAnchorStore("https://a.example", b"k" * 32, client=SimpleNamespace(get=lambda *a: Resp(404), put=lambda *a, **k: Resp(204))).close()


def _oidc(client=None, **kw) -> OIDCVerifier:
    base = dict(jwks_url="https://id.example/jwks", issuer="https://id.example", audience="aud", algorithms=["RS256"], client=client or SimpleNamespace())
    base.update(kw)
    return OIDCVerifier(**base)


def test_oidc_verify_branch_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key="key"), close=lambda: None)
    verifier = _oidc(client)
    monkeypatch.setattr(jwt, "get_unverified_header", lambda token: {"alg": "HS256", "kid": "k"})
    with pytest.raises(jwt.InvalidAlgorithmError):
        verifier.verify("t", require_auth_time=False)

    monkeypatch.setattr(jwt, "get_unverified_header", lambda token: {"alg": "RS256", "kid": "k"})
    monkeypatch.setattr(jwt, "decode", lambda *a, **k: {"aud": 7})
    with pytest.raises(jwt.InvalidAudienceError):
        verifier.verify("t", require_auth_time=False)

    monkeypatch.setattr(jwt, "decode", lambda *a, **k: {"aud": "aud", "nonce": 7})
    with pytest.raises(jwt.InvalidTokenError, match="nonce"):
        verifier.verify("t", expected_nonce="n", require_auth_time=False)
    monkeypatch.setattr(jwt, "decode", lambda *a, **k: {"aud": "aud", "nonce": "bad"})
    with pytest.raises(jwt.InvalidTokenError, match="nonce"):
        verifier.verify("t", expected_nonce="n", require_auth_time=False)
    monkeypatch.setattr(jwt, "decode", lambda *a, **k: {"aud": "aud", "nonce": "n"})
    assert verifier.verify("t", expected_nonce="n", require_auth_time=False)["aud"] == "aud"
    verifier.close()
    _oidc(SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key="key"))).close()


def _service(repo=None, policy=None, **kw) -> IngestionService:
    return IngestionService(
        repo or SimpleNamespace(), SimpleNamespace(), policy or SimpleNamespace(),
        ExtractionSettings(ocr_enabled=False, ocr_languages="eng"), SimpleNamespace(), **kw
    )


def test_ingestion_constructor_source_and_path_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="governance"):
        _service(require_corpus_governance=True)
    with pytest.raises(ValueError, match="reviewer credential"):
        _service(require_reviewer_credentials=True)
    with pytest.raises(ValueError, match="source signature"):
        _service(require_source_signature=True)

    s = _service()
    s._verify_source("issuer", VersionCreate(revision="1"), "a" * 64)
    signed = VersionCreate(revision="1", source_key_id="key", source_signature_b64="A" * 40)
    with pytest.raises(ValueError, match="trust profile"):
        s._verify_source("issuer", signed, "a" * 64)

    with pytest.raises(ValueError, match="empty document"):
        s._validate_path_and_hash(tmp_path / "missing", None)
    p = tmp_path / "x"
    p.write_bytes(b"abc")
    with pytest.raises(ValueError, match="digest mismatch"):
        s._validate_path_and_hash(p, "a" * 64)
    assert len(s._validate_path_and_hash(p, None)) == 64


def _actor(subject="reviewer") -> Identity:
    return Identity(subject=subject, roles=frozenset({"reviewer", "curator", "admin"}), clearance=AccessTier.RESTRICTED, corpora=frozenset({"public"}))


def _transition(target: ReviewState) -> ReviewTransition:
    return ReviewTransition(target=target, note="sufficient review note")


class Policy:
    def __init__(self, allowed=True): self.allowed = allowed
    def require(self, actor, permission): del actor, permission
    def can_access_document(self, actor, document): del actor, document; return SimpleNamespace(allowed=self.allowed)


class Repo:
    def __init__(self, version=None, document=None): self.version, self.document = version, document
    def get_version(self, actor, id): del actor, id; return self.version
    def get_document(self, actor, id): del actor, id; return self.document
    def transition_version(self, *a, **k): return "ok"


def _version(state=ReviewState.QUARANTINED, **kw):
    base = dict(
        id=uuid4(), document_id=uuid4(), review_state=state,
        authority=AuthorityClass.OFFICIAL_UA, in_force_from=datetime(2026,1,1,tzinfo=UTC).date(),
        metadata_reviewed_by=None, content_reviewed_by=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_ingestion_transition_refusal_matrix() -> None:
    actor = _actor()
    with pytest.raises(LookupError, match="version"):
        _service(Repo(None, None), Policy()).transition(actor, uuid4(), _transition(ReviewState.METADATA_REVIEWED))
    v = _version()
    with pytest.raises(LookupError, match="document"):
        _service(Repo(v, None), Policy()).transition(actor, v.id, _transition(ReviewState.METADATA_REVIEWED))
    with pytest.raises(PermissionError, match="access"):
        _service(Repo(v, SimpleNamespace()), Policy(False)).transition(actor, v.id, _transition(ReviewState.METADATA_REVIEWED))
    with pytest.raises(ValueError, match="invalid review transition"):
        _service(Repo(_version(ReviewState.REJECTED), SimpleNamespace()), Policy()).transition(actor, v.id, _transition(ReviewState.METADATA_REVIEWED))
    nonnorm = _version(ReviewState.CONTENT_REVIEWED, authority=AuthorityClass.ADVERSARY)
    with pytest.raises(ValueError, match="cannot be approved"):
        _service(Repo(nonnorm, SimpleNamespace()), Policy()).transition(actor, nonnorm.id, _transition(ReviewState.APPROVED))
    nodate = _version(ReviewState.CONTENT_REVIEWED, in_force_from=None)
    with pytest.raises(ValueError, match="effective_from"):
        _service(Repo(nodate, SimpleNamespace()), Policy()).transition(actor, nodate.id, _transition(ReviewState.APPROVED))
    same = _version(ReviewState.METADATA_REVIEWED, metadata_reviewed_by=actor.subject)
    with pytest.raises(ValueError, match="content reviewer"):
        _service(Repo(same, SimpleNamespace()), Policy(), review_separation_required=True).transition(actor, same.id, _transition(ReviewState.CONTENT_REVIEWED))
    prior = _version(ReviewState.CONTENT_REVIEWED, metadata_reviewed_by=actor.subject)
    with pytest.raises(ValueError, match="approver"):
        _service(Repo(prior, SimpleNamespace()), Policy(), review_separation_required=True).transition(actor, prior.id, _transition(ReviewState.APPROVED))
    valid = _version(ReviewState.QUARANTINED)
    service = _service(Repo(valid, SimpleNamespace()), Policy(), require_reviewer_credentials=True, reviewer_registry=SimpleNamespace(authorize=lambda **k: "cred"))
    service.reviewer_registry = None
    with pytest.raises(PermissionError, match="registry"):
        service.transition(actor, valid.id, _transition(ReviewState.METADATA_REVIEWED))
