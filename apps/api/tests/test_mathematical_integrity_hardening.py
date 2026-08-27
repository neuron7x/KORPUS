from __future__ import annotations

import pytest
from korpus.application.assurance_calculus import EvidenceClass, EvidencePoint
from korpus.application.embedding_coverage import assess_embedding_coverage
from korpus.application.embedding_migration import rollback_available, switch_admissible
from korpus.application.engineering_readiness import evaluate_engineering_profile
from korpus.application.evidence import contradiction_reason
from korpus.application.inference_budget import InferenceBudget, InferenceCycle
from korpus.application.plasticity import (
    AdaptationPolicy,
    AdaptationState,
    ObservationWindow,
    RuntimeKnobs,
)
from korpus.application.resilience import AdmissionController, CircuitBreaker
from korpus.application.retrieval import AUTHORITY_PRIOR, HybridLexicalRetriever
from korpus.application.tuning import JudgedCandidate, _simplex_weight_candidates
from korpus.domain.models import AuthorityClass
from korpus.domain.tenancy import PlanRecord
from korpus.infrastructure.liqpay import _amount_minor, _provider_datetime
from pydantic import ValidationError

import scripts.check_coverage_thresholds as coverage_thresholds
import scripts.run_local_production_preflight as local_preflight
import scripts.run_mutation_production_gate as mutation_gate
from scripts.coverage_gap_plan import build_plan

SOURCE = "a" * 64
RELEASE = "v-test"


def _readiness_profile(target: object = 50.0) -> dict[str, object]:
    return {
        "profile_id": "math-hardening",
        "target_percent": target,
        "dimensions": {
            "d": {
                "weight": 1.0,
                "evidence_class": "EXECUTED",
                "criteria": ["c"],
            }
        },
        "hard_external_predicates": ["c"],
    }


def _readiness_evidence(value: object) -> dict[str, object]:
    return {
        "dimensions": {
            "d": {
                "status": "PASS",
                "source_tree_sha256": SOURCE,
                "release": RELEASE,
                "criteria": {"c": value},
            }
        }
    }


@pytest.mark.parametrize("truthy_non_bool", ["false", "FAIL", 1, [False], {"status": "FAIL"}])
def test_readiness_criteria_reject_truthy_non_booleans(truthy_non_bool: object) -> None:
    with pytest.raises(ValueError, match="criterion results must be booleans"):
        evaluate_engineering_profile(
            _readiness_profile(),
            _readiness_evidence(truthy_non_bool),
            source_digest=SOURCE,
            release=RELEASE,
        )


@pytest.mark.parametrize("target", [float("nan"), float("inf"), -1.0, 100.000001])
def test_readiness_target_is_finite_probability_scale(target: float) -> None:
    with pytest.raises(ValueError, match="target_percent"):
        evaluate_engineering_profile(
            _readiness_profile(target),
            _readiness_evidence(True),
            source_digest=SOURCE,
            release=RELEASE,
        )


def test_lower_evidence_class_cannot_claim_independent_attested_flags() -> None:
    with pytest.raises(ValueError, match="INDEPENDENT_ATTESTED"):
        EvidencePoint(
            EvidenceClass.EXECUTED_WITH_NEGATIVE_CONTROL,
            SOURCE,
            RELEASE,
            "PASS",
            executed=True,
            negative_control=True,
            independent=True,
            attested=True,
        )


def test_attestation_without_independence_is_impossible() -> None:
    with pytest.raises(ValueError, match="must also be independent"):
        EvidencePoint(
            EvidenceClass.EXECUTED,
            SOURCE,
            RELEASE,
            "PASS",
            executed=True,
            attested=True,
        )


class _RepositoryStub:
    pass


def test_inverted_authority_priors_are_rejected_before_retrieval() -> None:
    priors = dict(AUTHORITY_PRIOR)
    priors[AuthorityClass.OFFICIAL_UA] = 0.2
    priors[AuthorityClass.ANALYTICAL] = 0.9
    with pytest.raises(ValueError, match="strictly preserve"):
        HybridLexicalRetriever(_RepositoryStub(), authority_priors=priors)  # type: ignore[arg-type]


def test_equal_normative_authority_priors_cannot_turn_class_order_into_similarity_tie() -> None:
    priors = dict(AUTHORITY_PRIOR)
    priors[AuthorityClass.OFFICIAL_UA] = priors[AuthorityClass.OFFICIAL_ALLIED]
    with pytest.raises(ValueError, match="strictly preserve"):
        HybridLexicalRetriever(_RepositoryStub(), authority_priors=priors)  # type: ignore[arg-type]


def test_non_normative_authority_cannot_reach_the_weakest_normative_rank() -> None:
    priors = dict(AUTHORITY_PRIOR)
    priors[AuthorityClass.ADVERSARY] = priors[AuthorityClass.HISTORICAL]
    with pytest.raises(ValueError, match="below historical"):
        HybridLexicalRetriever(_RepositoryStub(), authority_priors=priors)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("total", "active", "other", "stale"),
    [(-1, 0, 0, 0), (10, -1, 0, 0), (10, 11, 0, 0), (10, 10, -1, 0), (10, 10, 0, 11)],
)
def test_embedding_coverage_rejects_impossible_count_snapshots(
    total: int, active: int, other: int, stale: int
) -> None:
    with pytest.raises(ValueError):
        assess_embedding_coverage(
            active_model_id="m",
            active_dimensions=8,
            spans_total=total,
            spans_embedded_active=active,
            spans_embedded_other_model=other,
            spans_stale_text=stale,
        )


def test_embedding_switch_cannot_treat_more_than_100_percent_as_complete() -> None:
    allowed, reason = switch_admissible(
        spans_total=10, spans_embedded_target=11, spans_stale_text=0
    )
    assert allowed is False
    assert "inconsistent" in reason


def test_rollback_cannot_treat_duplicate_count_as_complete() -> None:
    allowed, reason = rollback_available(spans_total=10, spans_embedded_source=11)
    assert allowed is False
    assert "inconsistent" in reason


@pytest.mark.parametrize("bad_price", [True, 1.0, "19900"])
def test_plan_money_domain_rejects_coerced_non_integer_types(bad_price: object) -> None:
    with pytest.raises(ValidationError):
        PlanRecord(code="strict", name="Strict", price_minor=bad_price, currency="UAH")


@pytest.mark.parametrize("bad_amount", [True, "NaN", "Infinity", "-Infinity", "1E1000000"])
def test_liqpay_amount_parser_is_total_and_bounded(bad_amount: object) -> None:
    with pytest.raises(ValueError):
        _amount_minor(bad_amount)


def test_liqpay_amount_parser_preserves_exact_minor_units() -> None:
    assert _amount_minor("199.00") == 19_900
    assert _amount_minor("1000000.00") == 100_000_000
    with pytest.raises(ValueError, match="exceeds"):
        _amount_minor("1000000.01")
    with pytest.raises(ValueError, match="sub-minor"):
        _amount_minor("199.001")


def test_provider_timestamp_does_not_interpret_boolean_as_epoch_second() -> None:
    assert _provider_datetime(True) is None
    assert _provider_datetime(False) is None
    assert _provider_datetime(float("nan")) is None
    assert _provider_datetime(float("inf")) is None


def test_convertible_units_share_one_exact_numeric_domain() -> None:
    assert contradiction_reason("Дистанція маршруту 1 км.", "Дистанція маршруту 1000 м.") is None
    assert (
        contradiction_reason("Дистанція маршруту 1 км.", "Дистанція маршруту 900 м.")
        == "numeric_conflict:length_m"
    )
    assert contradiction_reason("Строк відповіді 1 год.", "Строк відповіді 60 хв.") is None
    assert (
        contradiction_reason("Строк відповіді 1 год.", "Строк відповіді 30 хв.")
        == "numeric_conflict:time_s"
    )


@pytest.mark.parametrize("bad_capacity", [True, 1.5, float("nan"), float("inf")])
def test_admission_capacity_is_a_finite_discrete_count(bad_capacity: object) -> None:
    with pytest.raises(ValueError, match="capacity"):
        AdmissionController(bad_capacity)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_timeout", [True, float("nan"), float("inf"), -0.1])
def test_admission_wait_timeout_is_finite(bad_timeout: object) -> None:
    with pytest.raises(ValueError, match="wait_timeout_seconds"):
        AdmissionController(2, bad_timeout)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_limit", [True, 1.5, 0, 3])
def test_subject_share_is_a_bounded_integer(bad_limit: object) -> None:
    with pytest.raises(ValueError, match="per_subject_limit"):
        AdmissionController(2, per_subject_limit=bad_limit)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_threshold", [True, 1.5, float("nan"), 0])
def test_circuit_failure_threshold_is_a_discrete_count(bad_threshold: object) -> None:
    with pytest.raises(ValueError, match="failure_threshold"):
        CircuitBreaker(bad_threshold, 1.0)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_timeout", [True, float("nan"), float("inf"), 0.0])
def test_circuit_recovery_timeout_is_finite_positive(bad_timeout: object) -> None:
    with pytest.raises(ValueError, match="recovery_timeout_seconds"):
        CircuitBreaker(1, bad_timeout)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [True, 1.5, float("nan"), float("inf")])
def test_inference_cycle_budget_cannot_be_disabled_by_non_integer_math(bad: object) -> None:
    with pytest.raises(ValueError):
        InferenceBudget(bad, 10, 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        InferenceBudget(3, bad, 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        InferenceBudget(3, 10, bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        InferenceCycle(bad, "d", frozenset({"e"}))  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [True, 1.5, float("nan"), float("inf")])
def test_plasticity_runtime_budgets_are_discrete_positive_counts(bad: object) -> None:
    with pytest.raises(ValueError, match="positive integers"):
        RuntimeKnobs(bad, 1200, 0.5, 0.5, 0.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="positive integers"):
        RuntimeKnobs(256, bad, 0.5, 0.5, 0.5)  # type: ignore[arg-type]


def test_plasticity_policy_rejects_nonfinite_latency_and_boolean_rate_domains() -> None:
    with pytest.raises(ValueError, match="healthy latency"):
        AdaptationPolicy(high_latency_ms=float("nan"))
    with pytest.raises(ValueError, match="rate policy"):
        AdaptationPolicy(high_error_rate=True)
    with pytest.raises(ValueError, match="max_safety_threshold"):
        AdaptationPolicy(max_safety_threshold=True)


def test_plasticity_observation_and_state_counters_are_discrete() -> None:
    with pytest.raises(ValueError, match="integers"):
        ObservationWindow(1.5, 200, 10.0, 0.0, 0.0, 0.0, 1.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="integers"):
        AdaptationState(RuntimeKnobs(32, 300, 0.5, 0.5, 0.5), last_change_sequence=True)


@pytest.mark.parametrize("bad", [True, 1.5, float("nan"), float("inf")])
def test_ranking_relevance_is_a_discrete_grade(bad: object) -> None:
    with pytest.raises(ValueError, match="integer"):
        JudgedCandidate("x", bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_step", [True, float("nan"), float("inf")])
def test_tuning_simplex_step_is_finite(bad_step: object) -> None:
    with pytest.raises(ValueError, match="finite"):
        list(_simplex_weight_candidates(bad_step))  # type: ignore[arg-type]


@pytest.mark.parametrize("impossible", [float("nan"), float("inf"), -1.0, 101.0])
def test_local_preflight_coverage_cannot_pass_impossible_percentages(impossible: float) -> None:
    policy = {"minimum_line_rate": 0.95, "minimum_branch_rate": 0.90}
    report = {"statement_coverage_percent": impossible, "branch_coverage_percent": 90.0}
    assert local_preflight._report_pass("coverage", report, policy) is False


def test_local_preflight_backend_does_not_treat_false_as_zero_failures() -> None:
    assert local_preflight._report_pass("backend", {"failed": False, "errors": 0}, {}) is False


def test_coverage_ratchet_rejects_impossible_totals_and_nan_policy(tmp_path) -> None:
    valid = {
        "totals": {
            "covered_lines": 96,
            "num_statements": 100,
            "covered_branches": 91,
            "num_branches": 100,
            "missing_branches": 9,
        },
        "files": {},
    }
    policy = {
        "coverage": {
            "minimum_statement_rate": 0.95,
            "minimum_branch_rate": 0.90,
            "baseline_missing_branches": 9,
            "maximum_missing_branch_regression": 0,
        },
        "risk_weights": {},
    }
    impossible = {**valid, "totals": valid["totals"] | {"covered_lines": 101}}
    with pytest.raises(ValueError, match="cannot exceed"):
        build_plan(impossible, policy, tmp_path)
    broken_policy = {
        **policy,
        "coverage": policy["coverage"] | {"minimum_branch_rate": float("nan")},
    }
    with pytest.raises(ValueError, match="finite"):
        build_plan(valid, broken_policy, tmp_path)


def test_standalone_coverage_threshold_parser_rejects_non_probability_policy() -> None:
    for bad in (True, float("nan"), float("inf"), -0.1, 1.1):
        with pytest.raises(ValueError):
            coverage_thresholds._unit_rate(bad)


def test_mutation_gate_counts_and_score_do_not_accept_boolean_arithmetic() -> None:
    assert mutation_gate._nonnegative_count(True) is None
    assert mutation_gate._score_is_exact_one(True) is False
    assert mutation_gate._score_is_exact_one(float("inf")) is False
    assert mutation_gate._score_is_exact_one(1.0) is True


@pytest.mark.parametrize(
    "section,path,bad",
    [
        ("eval", ("pass_rate",), "Infinity"),
        ("eval", ("audit_valid",), "false"),
        ("eval", ("citation_failures",), False),
        ("mutation", ("mutation_score",), "Infinity"),
        ("migration", ("table_set_match",), "false"),
        ("scale", ("results", "top1_recall"), "Infinity"),
        ("scale", ("results", "candidate_count"), False),
        ("scale", ("results", "query_latency_ms_p95"), -1),
    ],
)
def test_operational_release_gate_rejects_mathematically_invalid_evidence(
    section: str, path: tuple[str, ...], bad: object
) -> None:
    from copy import deepcopy

    from apps.api.tests.test_operations import evaluate, passing_reports

    reports = deepcopy(passing_reports())
    target = reports[section]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = bad
    assert evaluate(reports).status == "FAIL"


def test_js_divergence_rejects_boolean_probability_mass() -> None:
    from korpus.application.operations import jensen_shannon_divergence

    with pytest.raises(ValueError, match="finite non-negative"):
        jensen_shannon_divergence([True, 1.0], [1.0, 1.0])


@pytest.mark.parametrize("bad_requests", [True, 1.5, "1"])
def test_production_reliability_requires_discrete_positive_request_counts(
    bad_requests: object,
) -> None:
    from copy import deepcopy

    from korpus.application.production_reliability import evaluate_reliability_evidence

    from apps.api.tests.test_production_reliability import _evidence

    internal, chaos, load, recovery = _evidence()
    load = deepcopy(load)
    for phase in ("load", "spike", "soak"):
        load[phase]["requests"] = bad_requests
    checks = evaluate_reliability_evidence(internal, chaos, load, recovery, source="s", release="v")
    assert checks["live_load_soak_executed"] is False
    assert not all(checks.values())


@pytest.mark.parametrize("bad_timeout", [True, float("nan"), float("inf"), 0.0, -1.0])
def test_gcp_identity_timeout_is_finite_positive(bad_timeout: object) -> None:
    from korpus.infrastructure.gcp_identity import MetadataIdentityProvider

    with pytest.raises(ValueError, match="timeout_seconds"):
        MetadataIdentityProvider(timeout_seconds=bad_timeout)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_skew", [True, 1.5, -1, float("nan"), float("inf")])
def test_gcp_identity_refresh_skew_is_discrete_nonnegative(bad_skew: object) -> None:
    from korpus.infrastructure.gcp_identity import MetadataIdentityProvider

    with pytest.raises(ValueError, match="refresh_skew_seconds"):
        MetadataIdentityProvider(refresh_skew_seconds=bad_skew)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_expiry", [True, 1.5, "3600", 0, -1])
def test_gcp_metadata_token_ttl_is_strict_positive_integer(bad_expiry: object) -> None:
    import httpx
    from korpus.infrastructure.gcp_identity import MetadataIdentityError, MetadataIdentityProvider

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                200,
                headers={"Metadata-Flavor": "Google"},
                json={"access_token": "token", "expires_in": bad_expiry, "token_type": "Bearer"},
            )
        )
    )
    with pytest.raises(MetadataIdentityError, match="invalid"):
        MetadataIdentityProvider(client=client).access_token()


@pytest.mark.parametrize("bad_token", [None, 123, [], {}])
def test_gcp_metadata_access_token_is_not_string_coerced(bad_token: object) -> None:
    import httpx
    from korpus.infrastructure.gcp_identity import MetadataIdentityError, MetadataIdentityProvider

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                200,
                headers={"Metadata-Flavor": "Google"},
                json={"access_token": bad_token, "expires_in": 3600, "token_type": "Bearer"},
            )
        )
    )
    with pytest.raises(MetadataIdentityError, match="invalid"):
        MetadataIdentityProvider(client=client).access_token()


@pytest.mark.parametrize(
    "field,bad",
    [
        ("ocr_enabled", "false"),
        ("max_pdf_pages", True),
        ("max_pdf_pages", 1.5),
        ("max_pdf_pages", "10"),
        ("ocr_total_timeout_seconds", True),
        ("ocr_total_timeout_seconds", 1.5),
    ],
)
def test_parser_ipc_rejects_numeric_and_boolean_coercion(field: str, bad: object) -> None:
    from korpus.infrastructure.parser_contracts import parse_parser_request

    request = {
        "path": "/tmp/x.pdf",
        "filename": "x.pdf",
        "mime_type": "application/pdf",
        "ocr_enabled": False,
        "ocr_languages": "ukr",
        "max_pdf_pages": 10,
        "ocr_total_timeout_seconds": 5,
    }
    request[field] = bad
    with pytest.raises(ValueError):
        parse_parser_request(request)


@pytest.mark.parametrize("bad_schema", [True, "1", 1.0])
def test_provenance_schema_version_is_a_strict_integer(bad_schema: object) -> None:
    from korpus.application.provenance import PROVENANCE_KEY, ProvenanceError, read_provenance

    block = {
        "schema_version": bad_schema,
        "source_digest": "a" * 64,
        "generator": "test",
        "generated_at": "2026-08-20T00:00:00+00:00",
    }
    with pytest.raises(ProvenanceError, match="unsupported provenance schema"):
        read_provenance({PROVENANCE_KEY: block})


@pytest.mark.parametrize("bad_schema", [True, "1", 1.0])
def test_admission_register_schema_version_is_a_strict_integer(
    tmp_path, bad_schema: object
) -> None:
    import json

    from korpus.application.admission import load_register

    path = tmp_path / "admission.json"
    path.write_text(json.dumps({"schema_version": bad_schema, "grounds": [{"id": "g"}]}))
    with pytest.raises(ValueError, match="unsupported admission register schema"):
        load_register(path)


@pytest.mark.parametrize(
    "field,bad",
    [
        ("clock_skew_seconds", float("nan")),
        ("clock_skew_seconds", float("inf")),
        ("max_auth_age_seconds", float("nan")),
        ("max_auth_age_seconds", float("inf")),
    ],
)
def test_oidc_freshness_cannot_be_disabled_by_nonfinite_policy(field: str, bad: object) -> None:
    from korpus.security.oidc import OIDCVerifier

    values = {
        "jwks_url": "https://id.example/jwks",
        "issuer": "https://id.example",
        "audience": "korpus",
        "algorithms": ["RS256"],
        "client": object(),
        field: bad,
    }
    with pytest.raises(ValueError):
        OIDCVerifier(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_auth_time", [True, "1", float("nan"), float("inf")])
def test_oidc_auth_time_requires_finite_numericdate(bad_auth_time: object) -> None:
    import jwt
    from korpus.security.oidc import OIDCVerifier

    verifier = OIDCVerifier(
        jwks_url="https://id.example/jwks",
        issuer="https://id.example",
        audience="korpus",
        algorithms=["RS256"],
        client=object(),
    )
    with pytest.raises(jwt.InvalidTokenError, match="auth_time claim is invalid"):
        verifier._validate_assurance({"auth_time": bad_auth_time})


@pytest.mark.parametrize(
    "field,bad",
    [
        ("candidate_budget", True),
        ("candidate_budget", 8.0),
        ("candidate_budget", float("nan")),
        ("candidate_budget", float("inf")),
        ("timeout_ms", True),
        ("timeout_ms", 10.0),
        ("timeout_ms", float("nan")),
        ("timeout_ms", float("inf")),
    ],
)
def test_retrieval_runtime_limits_are_discrete_and_finite(field: str, bad: object) -> None:
    from korpus.application.retrieval import HybridLexicalRetriever

    values = {"candidate_budget": 8, "timeout_ms": 10, field: bad}
    with pytest.raises(ValueError):
        HybridLexicalRetriever(object(), **values)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_count", ["0.9", "-1", "NaN", "Infinity", "+1", "1e2"])
def test_junit_counts_reject_non_integer_cardinalities(tmp_path, bad_count: str) -> None:
    import xml.etree.ElementTree as ET

    from korpus.application.junit_contracts import junit_counts

    path = tmp_path / "bad.xml"
    path.write_text(f'<testsuite tests="62" failures="{bad_count}" errors="0" skipped="0"/>')
    with pytest.raises(ValueError):
        junit_counts(ET.parse(path).getroot())


def test_junit_counts_reject_impossible_outcome_cardinality(tmp_path) -> None:
    import xml.etree.ElementTree as ET

    from korpus.application.junit_contracts import junit_counts

    path = tmp_path / "impossible.xml"
    path.write_text('<testsuite tests="1" failures="1" errors="1" skipped="0"/>')
    with pytest.raises(ValueError, match="cannot exceed tests"):
        junit_counts(ET.parse(path).getroot())


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 1.5, True])
def test_object_store_size_limit_is_a_discrete_finite_count(tmp_path, bad: object) -> None:
    from korpus.infrastructure.object_store import LocalObjectStore

    with pytest.raises(ValueError):
        LocalObjectStore(tmp_path / "objects", max_object_bytes=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("max_attempts", float("nan")),
        ("max_attempts", 1.5),
        ("max_attempts", True),
        ("max_response_bytes", float("nan")),
        ("max_response_bytes", 1024.5),
        ("timeout_seconds", float("nan")),
        ("timeout_seconds", float("inf")),
        ("dimensions", 8.0),
        ("dimensions", True),
    ],
)
def test_embedding_resource_bounds_reject_nonfinite_or_nondiscrete_values(
    field: str, bad: object
) -> None:
    from korpus.infrastructure.semantic import HttpEmbeddingProvider

    class Dummy:
        def close(self) -> None:
            pass

    values = dict(
        endpoint="https://embed.example/v1", model_id="embed-1", dimensions=8, client=Dummy()
    )
    values[field] = bad
    with pytest.raises(ValueError):
        HttpEmbeddingProvider(**values)  # type: ignore[arg-type]


def test_local_object_store_put_bytes_enforces_max_object_bytes(tmp_path) -> None:
    import hashlib

    from korpus.infrastructure.object_store import LocalObjectStore

    content = b"ab"
    store = LocalObjectStore(tmp_path / "objects", max_object_bytes=1)
    with pytest.raises(ValueError, match="size limit"):
        store.put(content, hashlib.sha256(content).hexdigest(), "x.bin")


def test_s3_object_store_put_bytes_enforces_max_object_bytes() -> None:
    import hashlib

    from korpus.infrastructure.object_store import S3ObjectStore

    class Dummy:
        pass

    content = b"ab"
    store = S3ObjectStore(bucket="abc", max_object_bytes=1, client=Dummy())
    with pytest.raises(ValueError, match="size limit"):
        store.put(content, hashlib.sha256(content).hexdigest(), "x.bin")


@pytest.mark.parametrize("bad_size", [True, 1.5, "1.5", "NaN", "Infinity"])
def test_gcs_metadata_size_rejects_noncanonical_counts_before_download(bad_size: object) -> None:
    from korpus.infrastructure.gcs import GcsObjectStore

    class Fake:
        downloaded = False

        def metadata(self, _key):
            return {"size": bad_size}

        def download(self, _key):
            self.downloaded = True
            return b"x"

    fake = Fake()
    store = GcsObjectStore(bucket="abc", max_object_bytes=4, gcs=fake)
    with pytest.raises((ValueError, RuntimeError)):
        store.get("objects/aa/aa/" + "a" * 64)
    assert fake.downloaded is False


def test_gcs_metadata_oversize_decimal_is_rejected_before_download() -> None:
    from korpus.infrastructure.gcs import GcsObjectStore

    class Fake:
        downloaded = False

        def metadata(self, _key):
            return {"size": "5"}

        def download(self, _key):
            self.downloaded = True
            return b"12345"

    fake = Fake()
    store = GcsObjectStore(bucket="abc", max_object_bytes=4, gcs=fake)
    with pytest.raises(RuntimeError, match="read limit"):
        store.get("objects/aa/aa/" + "a" * 64)
    assert fake.downloaded is False
