from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from korpus.application import pec_hosted_evidence as hosted
from korpus.application import pec_metamorphic_eval as meta
from korpus.application.cache import EvidenceQueryCache
from korpus.application.pec_cache import PECCachedRetriever
from korpus.application.production_hard_predicates import (
    _all_checks,
    evaluate_hard_predicates,
    external_predicate_state,
    load_hard_predicate_profile,
)
from korpus.application.release_claims import _claim_status
from korpus.domain.models import Identity
from korpus.infrastructure.gcp_identity import MetadataIdentityError, MetadataIdentityProvider

from apps.api.tests.helpers import StubSnapshotReader

SHA = "a" * 64


def binding_payload() -> dict[str, object]:
    return {
        "release": "v0.9.7",
        "revision": "rev-1",
        "profile": "profile-1",
        "phase": "CANARY",
        "environment_class": "PRODUCTION",
        "training_receipt_sha256": SHA,
    }


def test_hosted_mapping_and_binding_cover_missing_and_invalid() -> None:
    assert hosted._mapping([]) is None
    assert hosted._mapping({"x": 1}) == {"x": 1}
    binding, failures = hosted._binding({"binding": binding_payload()}, "v0.9.7")
    assert binding is not None and failures == []
    binding, failures = hosted._binding({}, "v0.9.7")
    assert binding is None and failures == ["binding:missing"]
    bad = binding_payload()
    bad["release"] = "v0.9.6"
    binding, failures = hosted._binding({"binding": bad}, "v0.9.7")
    assert binding is None and failures and failures[0].startswith("binding:")


def test_hosted_audit_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    binding, _ = hosted._binding({"binding": binding_payload()}, "v0.9.7")
    assert hosted._audit({}, binding)[2] == ["audit_trace:missing"]
    monkeypatch.setattr(
        hosted, "extract_audit_trace", lambda rows, b: SimpleNamespace(event_ids=(), sha256="empty")
    )
    assert hosted._audit({"audit_rows": []}, binding) == (False, "empty", ["audit_trace:empty"])
    monkeypatch.setattr(
        hosted,
        "extract_audit_trace",
        lambda rows, b: SimpleNamespace(event_ids=("e1",), sha256="ok"),
    )
    assert hosted._audit({"audit_rows": [{}]}, binding) == (True, "ok", [])
    monkeypatch.setattr(
        hosted, "extract_audit_trace", lambda rows, b: (_ for _ in ()).throw(ValueError("bad"))
    )
    assert hosted._audit({"audit_rows": [{}]}, binding)[2] == ["audit_trace:bad"]


def test_hosted_training_judgment_and_receipt_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    binding, _ = hosted._binding({"binding": binding_payload()}, "v0.9.7")
    assert hosted._training({}, binding)[1] == ["training_lineage:missing"]
    monkeypatch.setattr(
        hosted,
        "validate_training_lineage",
        lambda *a, **k: SimpleNamespace(valid=True, failures=()),
    )
    evidence = {"training_receipt": {"receipt_sha256": SHA}, "training_dataset_sha256": "b" * 64}
    assert hosted._training(evidence, binding) == (True, [])
    evidence["training_receipt"] = {"receipt_sha256": "b" * 64}
    ok, failures = hosted._training(evidence, binding)
    assert not ok and "training_lineage:receipt_binding" in failures

    assert hosted._judgments({}, binding)[2] == ["human_judgments:missing"]
    monkeypatch.setattr(
        hosted,
        "evaluate_human_judgments",
        lambda *a, **k: SimpleNamespace(admissible=True, judgments=2, failures=()),
    )
    assert hosted._judgments({"expected_case_ids": ["a"], "judgments": [{}]}, binding) == (
        True,
        2,
        [],
    )

    assert hosted._hosted({}, release="v0.9.7", source_digest=SHA)[1] == ["hosted_evidence:missing"]
    receipt = {
        "provider": "github-actions",
        "run_id": "1",
        "workflow": "w",
        "release": "v0.9.7",
        "source_digest": SHA,
        "local_self_attested": False,
    }
    assert hosted._hosted({"hosted_receipt": receipt}, release="v0.9.7", source_digest=SHA) == (
        True,
        [],
    )


def test_hosted_authority_canary_and_top_level(monkeypatch: pytest.MonkeyPatch) -> None:
    binding, _ = hosted._binding({"binding": binding_payload()}, "v0.9.7")
    monkeypatch.setattr(hosted, "_binding", lambda e, r: (binding, []))
    monkeypatch.setattr(hosted, "_audit", lambda e, b: (True, "trace", []))
    monkeypatch.setattr(hosted, "_training", lambda e, b: (True, []))
    monkeypatch.setattr(hosted, "_judgments", lambda e, b: (True, 3, []))
    monkeypatch.setattr(hosted, "_hosted", lambda e, **k: (True, []))
    evidence = {"schema": "korpus.pec-production-evidence.v1", "source_digest": SHA}
    authority, got_binding, failures = hosted._authority_gate(
        evidence,
        release="v0.9.7",
        source_digest=SHA,
        attestation_verified=True,
        trusted_signer=True,
        signer_fingerprint="fp",
    )
    assert authority["status"] == "PASS" and got_binding == binding and failures == []

    monkeypatch.setattr(hosted, "evaluate_canary", lambda *a, **k: SimpleNamespace(failures=()))
    evidence.update({"canary": {}, "cloud_run_revision": "rev-1"})
    canary = hosted._canary_gate(
        evidence, authority=authority, binding=binding, release="v0.9.7", source_digest=SHA
    )
    assert canary["status"] == "PASS"

    result = hosted.evaluate_pec_production_evidence(
        evidence,
        release="v0.9.7",
        source_digest=SHA,
        attestation_verified=True,
        trusted_signer=True,
    )
    assert result["status"] == "PASS"

    missing = hosted._canary_gate(
        {}, authority={"status": "FAIL"}, binding=None, release="v0.9.7", source_digest=SHA
    )
    assert missing["status"] == "FAIL"


def _meta_row(pair: str, variant: str, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "pair_id": pair,
        "variant": variant,
        "source_digest": SHA,
        "corpus_release_id": "1" * 64,
        "evaluation_protocol_sha256": "b" * 64,
        "answer_calibration_id": "cal-1",
    }
    row.update(extra)
    return row


def test_metamorphic_eval_pass_unknown_and_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(meta, "metamorphic_issues", lambda base, row: [])
    rows = [_meta_row("p1", "base"), _meta_row("p1", "transformed", transformation_id="t1")]
    passed = meta.evaluate_metamorphic_pairs(rows, minimum_pairs=1)
    assert passed["status"] == "PASS" and passed["binding_completeness"] == "PASS"
    assert meta.evaluate_metamorphic_pairs(rows, minimum_pairs=2)["status"] == "UNKNOWN"
    incomplete = meta.evaluate_metamorphic_pairs([_meta_row("", "base")], minimum_pairs=1)
    assert incomplete["status"] == "FAIL"


def test_metamorphic_eval_binding_and_issue_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(meta, "metamorphic_issues", lambda base, row: ["semantic_drift"])
    transformed = _meta_row("p1", "transformed", transformation_id="t")
    transformed["source_digest"] = "c" * 64
    report = meta.evaluate_metamorphic_pairs(
        [_meta_row("p1", "base"), transformed], minimum_pairs=1
    )
    assert report["status"] == "FAIL"
    issues = [issue for failure in report["failures"] for issue in failure["issues"]]
    assert "semantic_drift" in issues and "artifact_binding_mismatch" in issues
    incomplete_binding = _meta_row("p2", "base")
    incomplete_binding["answer_calibration_id"] = ""
    transformed2 = dict(incomplete_binding)
    transformed2["variant"] = "transformed"
    monkeypatch.setattr(meta, "metamorphic_issues", lambda base, row: [])
    report2 = meta.evaluate_metamorphic_pairs([incomplete_binding, transformed2], minimum_pairs=1)
    assert report2["status"] == "FAIL"
    assert report2["binding_completeness"] == "UNKNOWN"


@pytest.mark.parametrize(
    ("content", "suffix", "expected"),
    [
        (None, ".json", "PENDING_EVIDENCE"),
        ("text", ".md", "SUPPORTED"),
        ("{", ".json", "INVALID_EVIDENCE"),
        ("[]", ".json", "INVALID_EVIDENCE"),
        (json.dumps({"release": "old"}), ".json", "STALE_EVIDENCE"),
        (json.dumps({"release": "v0.9.7", "source_digest": "b" * 64}), ".json", "STALE_EVIDENCE"),
        (
            json.dumps({"release": "v0.9.7", "source_digest": SHA, "status": "PASS"}),
            ".json",
            "SUPPORTED",
        ),
        (
            json.dumps({"release": "v0.9.7", "source_digest": SHA, "status": "FAIL"}),
            ".json",
            "REFUTED_BY_EVIDENCE",
        ),
    ],
)
def test_release_claim_status_branches(
    tmp_path: Path, content: str | None, suffix: str, expected: str
) -> None:
    relative = f"evidence{suffix}"
    if content is not None:
        (tmp_path / relative).write_text(content, encoding="utf-8")
    assert _claim_status(tmp_path, relative, SHA, "v0.9.7") == expected


class _Repo:
    corpus_snapshot_reader = StubSnapshotReader("e" * 64)


class _Delegate:
    def __init__(self) -> None:
        self.calls = 0

    def search(self, *args: object, **kwargs: object) -> list[object]:
        self.calls += 1
        return []


class _SemanticDelegate(_Delegate):
    def semantic_available(self) -> bool:
        return True

    def search_with_semantic(
        self, *args: object, semantic_enabled: bool, **kwargs: object
    ) -> list[object]:
        self.calls += 1
        return []


def _identity() -> Identity:
    return Identity(subject="u", corpora=frozenset({"c"}))


def test_pec_cache_semantic_availability_and_fallback() -> None:
    basic = _Delegate()
    cached = PECCachedRetriever(_Repo(), basic, EvidenceQueryCache(), "cfg")  # type: ignore[arg-type]
    assert cached.semantic_available() is False
    assert (
        cached.search_with_semantic(
            _identity(), "q", frozenset({"c"}), date(2026, 8, 23), semantic_enabled=True
        )
        == []
    )
    assert basic.calls == 1


def test_pec_cache_mode_keys_and_semantic_cache_hit() -> None:
    delegate = _SemanticDelegate()
    cached = PECCachedRetriever(_Repo(), delegate, EvidenceQueryCache(), "cfg")  # type: ignore[arg-type]
    assert cached.semantic_available() is True
    lex = cached._mode_key(_identity(), "q", frozenset({"c"}), date(2026, 8, 23), 8, False)
    sem = cached._mode_key(_identity(), "q", frozenset({"c"}), date(2026, 8, 23), 8, True)
    assert lex != sem
    args = (_identity(), "q", frozenset({"c"}), date(2026, 8, 23))
    assert cached.search_with_semantic(*args, semantic_enabled=True) == []
    assert cached.search_with_semantic(*args, semantic_enabled=True) == []
    assert delegate.calls == 1


def test_gcp_id_token_cache_invalid_payload_marker_and_close() -> None:
    calls: list[httpx.Request] = []
    token = "a" * 12 + "." + "b" * 12 + "." + "c" * 12

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, headers={"Metadata-Flavor": "Google"}, text=token)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = MetadataIdentityProvider(client=client, clock=lambda: 0.0)
    assert provider.id_token("https://service.example") == token
    assert provider.id_token("https://service.example") == token
    assert len(calls) == 1
    provider.close()

    invalid = MetadataIdentityProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, headers={"Metadata-Flavor": "Google"}, text="bad")
            )
        )
    )
    with pytest.raises(MetadataIdentityError, match="ID-token"):
        invalid.id_token("https://service.example")

    hostile = MetadataIdentityProvider(
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    headers={"Metadata-Flavor": "Hostile"},
                    json={"access_token": "x", "expires_in": 10, "token_type": "Bearer"},
                )
            )
        )
    )
    with pytest.raises(MetadataIdentityError, match="marker"):
        hostile.access_token()


def test_production_hard_predicate_validation_branches(tmp_path: Path) -> None:
    p = tmp_path / "profile.json"
    p.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_hard_predicate_profile(p)
    p.write_text(json.dumps({"predicates": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty"):
        load_hard_predicate_profile(p)
    assert _all_checks({"checks": []}, ("a",)) == (False, ("a",))
    with pytest.raises(ValueError, match="unknown"):
        external_predicate_state("does-not-exist", {})
    with pytest.raises(ValueError, match="no predicates"):
        evaluate_hard_predicates(tmp_path, {"predicates": ()}, {})
    with pytest.raises(ValueError, match="object"):
        evaluate_hard_predicates(tmp_path, {"predicates": ["bad"]}, {})


from typing import Any

from korpus.application.ports import ObjectStoreUnavailable
from korpus.infrastructure.gcs import GcsJsonClient, GcsObjectStore, GcsPreconditionFailed


class _GcsIdentity:
    def authorization_header(self) -> str:
        return "Bearer t"

    def close(self) -> None:
        self.closed = True


def _gcs_client(handler: Any) -> GcsJsonClient:
    return GcsJsonClient(
        "korpus-objects",
        identity=_GcsIdentity(),  # type: ignore[arg-type]
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_gcs_json_metadata_download_bucket_and_invalid_payloads() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/download/" in path:
            return httpx.Response(200, content=b"abc")
        if path.endswith("/missing"):
            return httpx.Response(404)
        if path.endswith("/invalid"):
            return httpx.Response(200, content=b"not-json")
        if path.endswith("/b/korpus-objects"):
            return httpx.Response(200, json={"name": "korpus-objects", "retentionPolicy": {}})
        return httpx.Response(200, json={"name": "objects/ok", "size": "3", "generation": "1"})

    g = _gcs_client(handler)
    assert g.download("objects/ok") == b"abc"
    assert g.metadata("missing") is None
    assert g.metadata("objects/ok") == {"name": "objects/ok", "size": "3", "generation": "1"}
    with pytest.raises(ObjectStoreUnavailable, match="metadata"):
        g.metadata("invalid")
    assert g.bucket_metadata()["name"] == "korpus-objects"

    bad_bucket = _gcs_client(lambda r: httpx.Response(200, content=b"bad"))
    with pytest.raises(ObjectStoreUnavailable, match="bucket metadata"):
        bad_bucket.bucket_metadata()


def test_gcs_json_upload_invalid_metadata_and_name_mismatch() -> None:
    with pytest.raises(ObjectStoreUnavailable, match="invalid metadata"):
        _gcs_client(lambda r: httpx.Response(200, content=b"bad")).upload_create_only(
            "objects/x", b"x"
        )
    with pytest.raises(ObjectStoreUnavailable, match="does not identify"):
        _gcs_client(lambda r: httpx.Response(200, json={"name": "other"})).upload_create_only(
            "objects/x", b"x"
        )


def test_gcs_json_list_paginates_and_respects_max_results() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert "pageToken" not in request.url.params
            return httpx.Response(
                200, json={"items": [{"name": "objects/a"}, {"name": ""}], "nextPageToken": "next"}
            )
        assert request.url.params["pageToken"] == "next"
        return httpx.Response(200, json={"items": [{"name": "objects/b"}]})

    g = _gcs_client(handler)
    assert g.list_names("objects/") == ["objects/a", "objects/b"]

    max_calls = 0

    def max_handler(request: httpx.Request) -> httpx.Response:
        nonlocal max_calls
        max_calls += 1
        return httpx.Response(
            200,
            json={"items": [{"name": "objects/a"}, {"name": "objects/b"}], "nextPageToken": "x"},
        )

    assert _gcs_client(max_handler).list_names("objects/", max_results=1) == ["objects/a"]
    assert max_calls == 1
    assert _gcs_client(max_handler).list_names("objects/", max_results=0) == []

    with pytest.raises(ObjectStoreUnavailable, match="list response"):
        _gcs_client(lambda r: httpx.Response(200, content=b"bad")).list_names("objects/")


def test_gcs_json_request_failure_modes_and_close() -> None:
    g = _gcs_client(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")))
    with pytest.raises(ObjectStoreUnavailable, match="transport"):
        g.download("x")

    with pytest.raises(ObjectStoreUnavailable, match="transient"):
        _gcs_client(lambda r: httpx.Response(503)).download("x")
    with pytest.raises(RuntimeError, match="request failed"):
        _gcs_client(lambda r: httpx.Response(403)).download("x")

    ident = _GcsIdentity()
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x"))
    )
    g2 = GcsJsonClient("korpus-objects", identity=ident, client=client)  # type: ignore[arg-type]
    g2.close()
    assert getattr(ident, "closed", False)


class _MemoryBackend:
    def __init__(self) -> None:
        self.bucket = "korpus-objects"
        self.objects: dict[str, bytes] = {}
        self.retention = 100
        self.fail_bucket = False
        self.closed = False

    def upload_create_only(self, name: str, content: bytes) -> dict[str, Any]:
        if name in self.objects:
            raise GcsPreconditionFailed("exists")
        self.objects[name] = bytes(content)
        return {"name": name, "size": str(len(content))}

    def download(self, name: str) -> bytes:
        return self.objects[name]

    def metadata(self, name: str) -> dict[str, Any] | None:
        if name not in self.objects:
            return None
        return {"name": name, "size": str(len(self.objects[name]))}

    def list_names(self, prefix: str, *, max_results: int | None = None) -> list[str]:
        names = sorted(x for x in self.objects if x.startswith(prefix))
        return names if max_results is None else names[:max_results]

    def bucket_metadata(self) -> dict[str, Any]:
        if self.fail_bucket:
            raise RuntimeError("down")
        return {"name": self.bucket, "retentionPolicy": {"retentionPeriod": str(self.retention)}}

    def close(self) -> None:
        self.closed = True


def _store2(backend: _MemoryBackend | None = None, **kwargs: Any) -> GcsObjectStore:
    b = backend or _MemoryBackend()
    return GcsObjectStore(bucket=b.bucket, prefix="objects", retention_seconds=100, gcs=b, **kwargs)  # type: ignore[arg-type]


def test_gcs_object_store_validation_size_exists_list_and_health(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="configuration"):
        GcsObjectStore(bucket="INVALID BUCKET", gcs=_MemoryBackend())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="configuration"):
        GcsObjectStore(bucket="korpus-objects", prefix="../bad", gcs=_MemoryBackend())  # type: ignore[arg-type]
    s = _store2(max_object_bytes=3)
    with pytest.raises(ValueError, match="source hash"):
        s._key("bad")
    with pytest.raises(ValueError, match="invalid object key"):
        s._validate_key("objects/not-a-key")
    with pytest.raises(ValueError, match="size"):
        s.put(b"four", "0" * 64, "x")
    p = tmp_path / "large"
    p.write_bytes(b"four")
    with pytest.raises(ValueError, match="size"):
        s.put_path(p, "0" * 64, "x")

    b = _MemoryBackend()
    s2 = _store2(b)
    digest = __import__("hashlib").sha256(b"abc").hexdigest()
    key = s2.put(b"abc", digest, "x")
    assert s2.exists(key) is True
    assert s2.list_keys() == {key}
    assert s2.healthcheck() is True
    b.retention = 1
    assert s2.healthcheck() is False
    b.retention = 100
    b.bucket = "other"
    assert s2.healthcheck() is False
    b.bucket = "korpus-objects"
    b.fail_bucket = True
    assert s2.healthcheck() is False
    s2.close()
    assert b.closed


def test_gcs_object_store_read_and_verify_failure_modes() -> None:
    b = _MemoryBackend()
    s = _store2(b, max_object_bytes=3)
    digest = __import__("hashlib").sha256(b"abc").hexdigest()
    key = s._key(digest)
    with pytest.raises(FileNotFoundError):
        s.get(key)
    b.objects[key] = b"abcd"
    with pytest.raises(RuntimeError, match="read limit"):
        s.get(key)
    b.objects[key] = b"abc"
    # lie about metadata size to exercise content-size check after download
    b.metadata = lambda name: {"name": name, "size": "3"}  # type: ignore[method-assign]
    b.download = lambda name: b"abcd"  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="read limit"):
        s.get(key)
    b.download = lambda name: b"bad"  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="integrity"):
        s.get(key)

    b.metadata = lambda name: None  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="missing after write"):
        s._verify_remote(key, digest, 3)
    b.metadata = lambda name: {"size": "2"}  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="length mismatch"):
        s._verify_remote(key, digest, 3)
    b.metadata = lambda name: {"size": "3"}  # type: ignore[method-assign]
    b.download = lambda name: b"bad"  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="integrity"):
        s._verify_remote(key, digest, 3)


from korpus.application.controller_profile import (
    ControllerLeaf,
    ControllerProfile,
    ControllerRule,
    FeatureRange,
    RuleCondition,
)
from korpus.application.evidence_state import feature_schema_sha256
from korpus.application.predictive_evidence_control import (
    PredictiveEvidenceController,
    _condition_matches,
    _support_failure,
)


def _controller_profile(
    *,
    admission_status: str = "PASS",
    rules: tuple[ControllerRule, ...] | None = None,
    minimum_leaf_samples: int = 1,
    risk_limit: float = 0.1,
) -> ControllerProfile:
    if rules is None:
        rules = (
            ControllerRule(
                rule_id="r1",
                conditions=(RuleCondition(feature="top1_score", operator="ge", value=0.5),),
                leaf=ControllerLeaf(
                    leaf_id="l1",
                    action="STOP_USE_CURRENT_EVIDENCE",
                    admitted=True,
                    observed_samples=10,
                    upper_error_bound=0.01,
                ),
            ),
        )
    return ControllerProfile(
        profile_id="profile-x",
        dataset_sha256="1" * 64,
        system_manifest_sha256="2" * 64,
        evaluation_protocol_sha256="3" * 64,
        replay_receipt_sha256="4" * 64,
        training_receipt_sha256="5" * 64,
        feature_schema_sha256=feature_schema_sha256(),
        corpus_release_id="b" * 64,
        answer_calibration_id="cal-v1",
        admission_status=admission_status,
        controller_risk_limit=risk_limit,
        minimum_leaf_samples=minimum_leaf_samples,
        rules=rules,
    )


class _State:
    def __init__(self, **values: object) -> None:
        self.values = {
            "top1_score": 0.7,
            "original_query_has_eligible_evidence": True,
            "semantic_available": True,
            **values,
        }
        self.fingerprint = "fp"
        self.original_query_has_eligible_evidence = bool(
            self.values.get("original_query_has_eligible_evidence")
        )
        self.semantic_available = bool(self.values.get("semantic_available"))
        self.retrieval_gate_passed = False
        self.minimum_admission_margin = 0.0
        self.decision_boundary_distance = 1.0

    def feature_value(self, name: str) -> object:
        return self.values.get(name)


def test_controller_profile_validation_and_artifact_binding_branches(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="minimum cannot exceed"):
        FeatureRange(minimum=2.0, maximum=1.0)
    with pytest.raises(ValueError, match="unknown PEC feature"):
        RuleCondition(feature="not-a-feature", operator="eq", value=1)
    with pytest.raises(ValueError, match="unknown PEC support"):
        ControllerLeaf(
            leaf_id="x",
            action="ABSTAIN",
            admitted=False,
            observed_samples=0,
            upper_error_bound=1.0,
            support={"bad": FeatureRange()},
        )

    good_leaf = ControllerLeaf(
        leaf_id="l", action="ABSTAIN", admitted=True, observed_samples=10, upper_error_bound=0.01
    )
    with pytest.raises(ValueError, match="rule ids"):
        _controller_profile(
            rules=(
                ControllerRule(rule_id="r", leaf=good_leaf),
                ControllerRule(
                    rule_id="r",
                    leaf=ControllerLeaf(
                        leaf_id="l2",
                        action="ABSTAIN",
                        admitted=True,
                        observed_samples=10,
                        upper_error_bound=0.01,
                    ),
                ),
            )
        )
    with pytest.raises(ValueError, match="leaf ids"):
        _controller_profile(
            rules=(
                ControllerRule(rule_id="r1", leaf=good_leaf),
                ControllerRule(rule_id="r2", leaf=good_leaf),
            )
        )
    with pytest.raises(ValueError, match="risk limit"):
        _controller_profile(
            risk_limit=0.01,
            rules=(
                ControllerRule(
                    rule_id="r",
                    leaf=ControllerLeaf(
                        leaf_id="l",
                        action="ABSTAIN",
                        admitted=True,
                        observed_samples=10,
                        upper_error_bound=0.02,
                    ),
                ),
            ),
        )

    profile = _controller_profile()
    path = tmp_path / "profile.json"
    path.write_text(profile.canonical_json(), encoding="utf-8")
    loaded = ControllerProfile.load(path)
    assert loaded.digest == profile.digest
    with pytest.raises(ValueError, match="profile digest"):
        ControllerProfile.load(path, expected_sha256="0" * 64)

    artifacts = []
    hashes = []
    for name in ("dataset", "manifest", "eval", "replay"):
        p = tmp_path / name
        p.write_bytes(name.encode())
        artifacts.append(p)
        hashes.append(__import__("hashlib").sha256(name.encode()).hexdigest())
    bound = profile.model_copy(
        update={
            "dataset_sha256": hashes[0],
            "system_manifest_sha256": hashes[1],
            "evaluation_protocol_sha256": hashes[2],
            "replay_receipt_sha256": hashes[3],
        }
    )
    bound.validate_artifact_bindings(
        dataset=artifacts[0],
        system_manifest=artifacts[1],
        evaluation_protocol=artifacts[2],
        replay_receipt=artifacts[3],
    )
    artifacts[0].unlink()
    with pytest.raises(ValueError, match="artifact is missing"):
        bound.validate_artifact_bindings(
            dataset=artifacts[0],
            system_manifest=artifacts[1],
            evaluation_protocol=artifacts[2],
            replay_receipt=artifacts[3],
        )
    artifacts[0].write_bytes(b"wrong")
    with pytest.raises(ValueError, match="digest mismatch"):
        bound.validate_artifact_bindings(
            dataset=artifacts[0],
            system_manifest=artifacts[1],
            evaluation_protocol=artifacts[2],
            replay_receipt=artifacts[3],
        )


def test_predictive_condition_operator_and_support_branches() -> None:
    state = _State(top1_score=2.0, original_query_has_eligible_evidence=True)
    assert _condition_matches(state, RuleCondition(feature="top1_score", operator="lt", value=3.0))
    assert _condition_matches(state, RuleCondition(feature="top1_score", operator="le", value=2.0))
    assert _condition_matches(state, RuleCondition(feature="top1_score", operator="gt", value=1.0))
    assert _condition_matches(state, RuleCondition(feature="top1_score", operator="ge", value=2.0))
    assert _condition_matches(state, RuleCondition(feature="top1_score", operator="ne", value=1.0))
    assert _condition_matches(state, RuleCondition(feature="top1_score", operator="eq", value=2.0))
    assert not _condition_matches(
        _State(top1_score=True), RuleCondition(feature="top1_score", operator="gt", value=1.0)
    )
    assert not _condition_matches(
        state, RuleCondition(feature="top1_score", operator="gt", value=True)
    )

    assert (
        _support_failure(_State(top1_score="x"), {"top1_score": FeatureRange(minimum=0.0)})
        == "unsupported_non_numeric_feature:top1_score"
    )
    assert (
        _support_failure(_State(top1_score=0.1), {"top1_score": FeatureRange(minimum=0.5)})
        == "state_below_support:top1_score"
    )
    assert (
        _support_failure(_State(top1_score=1.1), {"top1_score": FeatureRange(maximum=1.0)})
        == "state_above_support:top1_score"
    )
    assert (
        _support_failure(
            _State(top1_score=0.7), {"top1_score": FeatureRange(minimum=0.5, maximum=1.0)}
        )
        is None
    )


def test_predictive_controller_binding_and_out_of_support_branches() -> None:
    state = _State()
    not_admitted = PredictiveEvidenceController(
        _controller_profile(admission_status="UNKNOWN"), shadow_mode=False
    ).decide(state, corpus_release_id="b" * 64, answer_calibration_id="cal-v1")
    assert not_admitted.fallback_reason == "profile_not_admitted"
    calibration = PredictiveEvidenceController(_controller_profile(), shadow_mode=False).decide(
        state, corpus_release_id="b" * 64, answer_calibration_id="other"
    )
    assert calibration.fallback_reason == "answer_calibration_mismatch"
    false_rule = ControllerRule(
        rule_id="false",
        conditions=(RuleCondition(feature="top1_score", operator="lt", value=0.0),),
        leaf=ControllerLeaf(
            leaf_id="lf",
            action="ABSTAIN",
            admitted=True,
            observed_samples=10,
            upper_error_bound=0.01,
        ),
    )
    out = PredictiveEvidenceController(
        _controller_profile(rules=(false_rule,)), shadow_mode=False
    ).decide(state, corpus_release_id="b" * 64, answer_calibration_id="cal-v1")
    assert out.fallback_reason == "state_out_of_support"


# --- v0.9.7 coverage closure: PEC research/config/search/knowledge + provenance ---


def test_pec_research_bounds_conditional_and_status_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from korpus.application import pec_research as research

    assert research.simultaneous_hoeffding_upper(0, 0, 0.1, 1) == 1.0
    with pytest.raises(ValueError, match="delta"):
        research.simultaneous_hoeffding_upper(0, 2, 1.0, 1)
    with pytest.raises(ValueError, match="hypotheses"):
        research.simultaneous_hoeffding_upper(0, 2, 0.1, 0)
    bad = research.conditional_risk_report(
        [{"stratum": "", "error": True}, {"stratum": "a", "error": "bad"}],
        stratum_key="stratum",
        error_key="error",
        risk_limit=1.0,
        delta=0.1,
        minimum_samples=1,
    )
    assert bad["status"] == "FAIL" and bad["invalid_rows"] == 2
    good = research.conditional_risk_report(
        [{"stratum": "a", "error": False}],
        stratum_key="stratum",
        error_key="error",
        risk_limit=1.0,
        delta=0.1,
        minimum_samples=1,
    )
    assert good["status"] == "PASS" and good["strata_total"] == 1
    assert research.research_status({"status": "FAIL"}, [{"status": "PASS"}]) == ("FAIL", False)
    assert research.research_status({"status": "PASS"}, [{"status": "PASS"}]) == ("PASS", True)
    assert research.research_status({"status": "PASS"}, [{"status": "UNKNOWN"}]) == (
        "UNKNOWN",
        True,
    )


def test_pec_research_ablation_replay_information_and_judgment_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from korpus.application import pec_research as research
    from korpus.application.pec_training import TrainingRow

    assert research.feature_ablation_generalization([]) == {
        "status": "UNKNOWN",
        "reason": "no_training_rows",
    }
    row = TrainingRow("q", "g", {"top1_score": 0.7}, "ABSTAIN")
    monkeypatch.setattr(research, "nested_group_validation", lambda rows: {"status": "UNKNOWN"})
    assert (
        research.feature_ablation_generalization([row])["reason"]
        == "nested_full_model_not_estimable"
    )
    calls = 0

    def validation(rows):
        nonlocal calls
        calls += 1
        return {"status": "PASS", "oof_accuracy": 0.8 if calls == 1 else 0.7}

    monkeypatch.setattr(research, "nested_group_validation", validation)
    ablation = research.feature_ablation_generalization([row])
    assert ablation["status"] == "PASS" and ablation["ablations"]

    assert research.replay_priority_enrichment([])["status"] == "UNKNOWN"
    assert (
        research.replay_priority_enrichment([{"out_of_support": True}], top_fraction=0)["status"]
        == "UNKNOWN"
    )
    monkeypatch.setattr(research, "replay_priority", lambda row: 0)
    replay = research.replay_priority_enrichment(
        [{"out_of_support": True}, {"out_of_support": False}], top_fraction=0.5, alpha=1.0
    )
    assert replay["rows"] == 2 and replay["failures"] == 1
    assert research._hypergeom_tail(0, 0, 0, 0) == 1.0
    monkeypatch.setattr(research.math, "comb", lambda *args: 0)
    assert research._hypergeom_tail(2, 1, 1, 1) == 1.0

    assert (
        research.observed_information_gain(
            [{"query_id": "", "action": "STOP_USE_CURRENT_EVIDENCE"}]
        )["status"]
        == "UNKNOWN"
    )
    info = research.observed_information_gain(
        [
            {
                "query_id": "q",
                "action": "STOP_USE_CURRENT_EVIDENCE",
                "retrieval_quality": {"x": 1.0},
                "search_count": 1,
            },
            {
                "query_id": "q",
                "action": "EXPAND",
                "retrieval_quality": {"x": 2.0},
                "gold_hit": True,
                "quality_ok": True,
                "search_count": 2,
            },
        ]
    )
    assert (
        info["status"] == "PASS" and info["comparisons"][0]["retrieval_quality_deltas"]["x"] == 1.0
    )

    assert (
        research.production_judgment_validity([{"id": "x", "production_judged": False}])["status"]
        == "UNKNOWN"
    )
    invalid = research.production_judgment_validity(
        [
            {
                "id": "x",
                "production_judged": True,
                "judgment_provenance_sha256": "bad",
                "adjudication_protocol": "",
            }
        ]
    )
    assert invalid["status"] == "FAIL" and len(invalid["invalid"]) == 2
    valid = research.production_judgment_validity(
        [
            {
                "id": "x",
                "production_judged": True,
                "judgment_provenance_sha256": "a" * 64,
                "adjudication_protocol": "p",
            }
        ]
    )
    assert valid["status"] == "PASS"


def _pec_settings(**updates: object) -> SimpleNamespace:
    base = dict(
        pec_enabled=False,
        pec_profile_sha256=None,
        pec_profile_path=None,
        contextual_retrieval_enabled=False,
        pec_dataset_path=None,
        pec_system_manifest_path=None,
        pec_evaluation_protocol_path=None,
        pec_replay_receipt_path=None,
        answer_policy_mode="calibrated",
    )
    base.update(updates)
    return SimpleNamespace(**base)


def test_pec_config_policy_all_admission_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import korpus.pec_config_policy as policy

    with pytest.raises(ValueError, match="digest is configured"):
        policy.validate_pec_settings(_pec_settings(pec_profile_sha256="a" * 64), controlled=False)
    with pytest.raises(ValueError, match="contextual retrieval"):
        policy.validate_pec_settings(
            _pec_settings(contextual_retrieval_enabled=True), controlled=True
        )
    policy.validate_pec_settings(_pec_settings(), controlled=False)
    with pytest.raises(ValueError, match="artifacts are missing"):
        policy.validate_pec_settings(_pec_settings(pec_enabled=True), controlled=False)

    paths = {}
    for name in ("profile", "dataset", "manifest", "evaluation", "replay"):
        path = tmp_path / name
        path.write_text(name)
        paths[name] = path
    enabled = _pec_settings(
        pec_enabled=True,
        pec_profile_path=paths["profile"],
        pec_dataset_path=paths["dataset"],
        pec_system_manifest_path=paths["manifest"],
        pec_evaluation_protocol_path=paths["evaluation"],
        pec_replay_receipt_path=paths["replay"],
    )
    with pytest.raises(ValueError, match="profile digest"):
        policy.validate_pec_settings(enabled, controlled=False)
    enabled.pec_profile_sha256 = "a" * 64
    enabled.answer_policy_mode = "other"
    with pytest.raises(ValueError, match="calibrated"):
        policy.validate_pec_settings(enabled, controlled=True)
    enabled.answer_policy_mode = "calibrated"
    fake = SimpleNamespace(
        admission_status="UNKNOWN", validate_artifact_bindings=lambda **kwargs: None
    )
    monkeypatch.setattr(policy.ControllerProfile, "load", lambda *a, **k: fake)
    with pytest.raises(ValueError, match="not admitted"):
        policy.validate_pec_settings(enabled, controlled=True)
    fake.admission_status = "PASS"
    policy.validate_pec_settings(enabled, controlled=True)


def test_repository_search_validation_alias_predicate_and_early_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from korpus.infrastructure import repository_search as rs

    identity = SimpleNamespace(corpora=frozenset({"c"}))
    with pytest.raises(ValueError, match="positive"):
        rs.search_retrievable_spans(
            SimpleNamespace(), identity, frozenset({"c"}), date.today(), "q", 0
        )
    assert (
        rs.search_retrievable_spans(
            SimpleNamespace(), identity, frozenset({"x"}), date.today(), "q", 1
        )
        == []
    )
    assert rs._alias_document_ids(("alpha",), {"doc": ("Alpha beta",), "other": ("gamma",)}) == [
        "doc"
    ]
    assert len(rs._context_predicates(("alpha",), ["doc"])) == 8
    with pytest.raises(ValueError, match="positive"):
        rs.search_contextual_retrievable_spans(
            SimpleNamespace(), identity, frozenset({"c"}), date.today(), "q", 0
        )
    monkeypatch.setattr(
        rs, "search_retrievable_spans", lambda *a, **k: [(SimpleNamespace(id="s"), None, None)]
    )
    assert (
        len(
            rs.search_contextual_retrievable_spans(
                SimpleNamespace(), identity, frozenset({"c"}), date.today(), "q", 1
            )
        )
        == 1
    )
    monkeypatch.setattr(rs, "search_retrievable_spans", lambda *a, **k: [])
    monkeypatch.setattr(rs, "_context_terms", lambda q: ())
    assert (
        rs.search_contextual_retrievable_spans(
            SimpleNamespace(), identity, frozenset({"c"}), date.today(), "q", 1
        )
        == []
    )
    monkeypatch.setattr(rs, "_context_terms", lambda q: ("alpha",))
    monkeypatch.setattr(rs, "_context_predicates", lambda terms, aliases: [])
    assert (
        rs.search_contextual_retrievable_spans(
            SimpleNamespace(), identity, frozenset({"c"}), date.today(), "q", 1
        )
        == []
    )


def test_repository_search_execution_and_baseline_exclusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from korpus.infrastructure import repository_search as rs

    class Result:
        def mappings(self):
            return self

        def all(self):
            return [{"span_id": "s2"}]

    class Conn:
        def execute(self, statement):
            return Result()

    class Begin:
        def __enter__(self):
            return Conn()

        def __exit__(self, *args):
            return False

    repo = SimpleNamespace(
        engine=SimpleNamespace(begin=Begin),
        _apply_postgres_identity=lambda *a: None,
        _candidate_span_ids=lambda *a: ["s1"],
    )
    identity = SimpleNamespace(corpora=frozenset({"c"}))

    class Statement:
        def where(self, *a):
            return self

        def limit(self, *a):
            return self

    monkeypatch.setattr(rs.retrieval_queries, "retrievable_projection", lambda *a, **k: Statement())
    monkeypatch.setattr(
        rs.retrieval_queries, "materialize_current", lambda rows, as_of, limit: list(rows)[:limit]
    )
    # Candidate id missing from result covers ordered filtering.
    assert rs.search_retrievable_spans(repo, identity, frozenset({"c"}), date.today(), "q", 2) == []
    repo._candidate_span_ids = lambda *a: []
    assert rs.search_retrievable_spans(repo, identity, frozenset({"c"}), date.today(), "q", 2) == []

    monkeypatch.setattr(
        rs, "search_retrievable_spans", lambda *a, **k: [(SimpleNamespace(id="s1"), None, None)]
    )
    monkeypatch.setattr(rs, "_context_terms", lambda q: ("alpha",))
    monkeypatch.setattr(rs, "_context_predicates", lambda *a: [True])
    result = rs.search_contextual_retrievable_spans(
        repo, identity, frozenset({"c"}), date.today(), "q", 2
    )
    assert result[0][0].id == "s1" and result[1]["span_id"] == "s2"


def _mk_binding(*, active: bool = True):
    from korpus.application.military_knowledge import EvidenceBinding

    return EvidenceBinding(
        document_id="d",
        version_id="v",
        span_ids=frozenset({"s"}),
        source_hash="a" * 64,
        effective_from=date(2020, 1, 1) if active else date(2030, 1, 1),
    )


def test_military_knowledge_validation_publication_and_neighborhood_branches() -> None:
    from korpus.application.military_knowledge import (
        EffectiveGraphIndex,
        KnowledgeNode,
        KnowledgeNodeKind,
        KnowledgeRelation,
        KnowledgeRelationKind,
        MilitaryKnowledgeGraph,
        effective_neighborhood,
    )

    active, future = _mk_binding(), _mk_binding(active=False)
    n1 = KnowledgeNode(id="n1", kind=KnowledgeNodeKind.DOCTRINE, label="one", bindings=(active,))
    n2 = KnowledgeNode(id="n2", kind=KnowledgeNodeKind.PROCEDURE, label="two", bindings=(future,))
    with pytest.raises(ValueError, match="target itself"):
        KnowledgeRelation(
            source_id="n1", target_id="n1", kind=KnowledgeRelationKind.REQUIRES, bindings=(active,)
        )
    with pytest.raises(ValueError, match="node ids"):
        MilitaryKnowledgeGraph(nodes=(n1, n1))
    rel = KnowledgeRelation(
        source_id="n1", target_id="n2", kind=KnowledgeRelationKind.SUPERSEDES, bindings=(future,)
    )
    with pytest.raises(ValueError, match="relation identities"):
        MilitaryKnowledgeGraph(nodes=(n1, n2), relations=(rel, rel))
    dangling = KnowledgeRelation(
        source_id="n1", target_id="missing", kind=KnowledgeRelationKind.REQUIRES, bindings=(active,)
    )
    with pytest.raises(ValueError, match="unknown nodes"):
        MilitaryKnowledgeGraph(nodes=(n1,), relations=(dangling,))
    graph = MilitaryKnowledgeGraph(nodes=(n1, n2), relations=(rel,))
    violations = graph.publication_violations(as_of=date(2026, 1, 1))
    assert any(x.startswith("node_without_effective_evidence:n2") for x in violations)
    assert any(x.startswith("relation_without_effective_evidence") for x in violations)
    with pytest.raises(ValueError, match="max_depth"):
        effective_neighborhood(graph, "n1", as_of=date(2026, 1, 1), max_depth=9)
    with pytest.raises(KeyError):
        effective_neighborhood(graph, "missing", as_of=date(2026, 1, 1))
    assert effective_neighborhood(
        graph,
        "n1",
        as_of=date(2026, 1, 1),
        relation_kinds=frozenset({KnowledgeRelationKind.REQUIRES}),
    ) == ("n1",)
    idx = EffectiveGraphIndex.build(graph, as_of=date(2026, 1, 1))
    with pytest.raises(ValueError, match="max_depth"):
        idx.neighborhood("n1", max_depth=-1)
    with pytest.raises(KeyError):
        idx.neighborhood("missing")
    assert idx.neighborhood("n1") == ("n1",)


def test_military_knowledge_cycle_and_effective_index_traversal() -> None:
    from korpus.application.military_knowledge import (
        EffectiveGraphIndex,
        KnowledgeNode,
        KnowledgeNodeKind,
        KnowledgeRelation,
        KnowledgeRelationKind,
        MilitaryKnowledgeGraph,
    )

    b = _mk_binding()
    nodes = tuple(
        KnowledgeNode(id=f"n{i}", kind=KnowledgeNodeKind.DOCTRINE, label=str(i), bindings=(b,))
        for i in range(3)
    )
    relations = (
        KnowledgeRelation(
            source_id="n0", target_id="n1", kind=KnowledgeRelationKind.SUPERSEDES, bindings=(b,)
        ),
        KnowledgeRelation(
            source_id="n1", target_id="n0", kind=KnowledgeRelationKind.SUPERSEDES, bindings=(b,)
        ),
        KnowledgeRelation(
            source_id="n1", target_id="n2", kind=KnowledgeRelationKind.REQUIRES, bindings=(b,)
        ),
    )
    graph = MilitaryKnowledgeGraph(nodes=nodes, relations=relations)
    assert any(
        v.startswith("supersession_cycle")
        for v in graph.publication_violations(as_of=date(2026, 1, 1))
    )
    idx = EffectiveGraphIndex.build(graph, as_of=date(2026, 1, 1))
    assert idx.neighborhood("n0", max_depth=3) == ("n0", "n1", "n2")


def test_source_digest_empty_git_tree_falls_back_to_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import importlib.util

    module_path = Path(__file__).parents[3] / "scripts" / "source_digest.py"
    spec = importlib.util.spec_from_file_location("source_digest_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_git", lambda *args: b"")
    monkeypatch.setattr(module, "_archive_paths", lambda: [Path("README.md")])
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "README.md").write_text("release", encoding="utf-8")
    assert module._git_paths("HEAD") is None
    digest = module.source_tree_digest("HEAD")
    assert digest != __import__("hashlib").sha256(b"").hexdigest()


def _load_source_digest_module():
    import importlib.util

    module_path = Path(__file__).parents[3] / "scripts" / "source_digest.py"
    spec = importlib.util.spec_from_file_location("source_digest_more_coverage", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_digest_inclusion_git_and_archive_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import subprocess

    module = _load_source_digest_module()
    assert module._included("README.md")
    assert not module._included("reports/x.json")
    assert not module._included("SOURCE_MANIFEST.json")

    monkeypatch.setattr(
        module, "_git", lambda *args: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "git"))
    )
    assert module._git_paths("HEAD") is None
    monkeypatch.setattr(module, "_git", lambda *args: b"reports/x.json\0README.md\0")
    assert module._git_paths("HEAD") == [Path("README.md")]

    monkeypatch.setattr(module, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="neither Git metadata"):
        module._archive_paths()
    manifest = tmp_path / "SOURCE_MANIFEST.json"
    manifest.write_text(json.dumps({"files": "bad"}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="invalid source manifest"):
        module._archive_paths()
    manifest.write_text(json.dumps({"files": ["bad"]}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="record"):
        module._archive_paths()
    manifest.write_text(
        json.dumps({"files": [{"path": "missing.txt", "sha256": "0" * 64}]}), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="missing or unsafe"):
        module._archive_paths()
    target = tmp_path / "a.txt"
    target.write_text("x", encoding="utf-8")
    manifest.write_text(
        json.dumps({"files": [{"path": "a.txt", "sha256": "0" * 64}]}), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="hash mismatch"):
        module._archive_paths()
    digest = __import__("hashlib").sha256(b"x").hexdigest()
    manifest.write_text(
        json.dumps(
            {"files": [{"path": "a.txt", "sha256": digest}, {"path": "reports/x", "sha256": "x"}]}
        ),
        encoding="utf-8",
    )
    assert module._archive_paths() == [Path("a.txt")]
    monkeypatch.setattr(
        module, "_git", lambda *args: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "git"))
    )
    assert module.included_paths() == [Path("a.txt")]


def test_source_digest_git_content_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_source_digest_module()
    monkeypatch.setattr(module, "ROOT", tmp_path)

    def fake_git(*args: str) -> bytes:
        if args[:4] == ("ls-tree", "-r", "-z", "--name-only"):
            return b"b.txt\0a.txt\0reports/x\0"
        if args[0] == "show":
            return {"HEAD:a.txt": b"A", "HEAD:b.txt": b"B"}[args[1]]
        raise AssertionError(args)

    monkeypatch.setattr(module, "_git", fake_git)
    assert module.included_paths() == [Path("a.txt"), Path("b.txt")]
    got = module.source_tree_digest()
    assert len(got) == 64 and got != __import__("hashlib").sha256(b"").hexdigest()


def test_pec_training_model_edge_and_candidate_branches() -> None:
    from korpus.application import pec_training_model as tm
    from korpus.application.controller_profile import RuleCondition

    assert tm.TreeModel(1, 1, ()).predict_leaf({}) is None
    assert tm.TreeModel(1, 1, ()).predict({}) == "BASELINE"
    assert not tm._matches(True, RuleCondition(feature="top1_score", operator="gt", value=0.5))
    assert not tm._matches(1.0, RuleCondition(feature="top1_score", operator="gt", value=True))
    assert tm._errors([]) == 0

    bool_rows = [
        tm.TrainingRow("q1", "g", {"original_query_has_eligible_evidence": False}, "A"),
        tm.TrainingRow("q2", "g", {"original_query_has_eligible_evidence": True}, "B"),
    ]
    assert any(c.operator == "eq" for c in tm._candidates(bool_rows))
    str_rows = [
        tm.TrainingRow("q1", "g", {"top1_score": "uk"}, "A"),
        tm.TrainingRow("q2", "g", {"top1_score": "en"}, "B"),
    ]
    assert any(c.operator == "eq" for c in tm._candidates(str_rows))
    numeric_rows = [
        tm.TrainingRow(str(i), "g", {"top1_score": float(i)}, "A" if i < 13 else "B")
        for i in range(30)
    ]
    candidates = list(tm._candidates(numeric_rows))
    assert candidates and all(c.operator == "le" for c in candidates)
    with pytest.raises(ValueError, match="requires rows"):
        tm.train_tree([], max_depth=1, min_leaf=1)
    model = tm.train_tree(numeric_rows, max_depth=2, min_leaf=1)
    assert model.leaves and model.predict({"top1_score": 0.0}) in {"A", "B"}
