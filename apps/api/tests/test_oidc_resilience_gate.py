from __future__ import annotations

from copy import deepcopy

from scripts.run_oidc_resilience_gate import validate_report


def valid_report():
    expected = {name: 20 for name in (
        "success", "http_503", "invalid_json", "transport", "wrong_token_type"
    )}
    return {
        "schema": "korpus.browser-oidc-resilience.v1",
        "candidate_commit": "a" * 40,
        "workload": {"operations": 100, "workers": 8, "recovery_operations": 10,
                     "expected": expected},
        "results": {"observed": deepcopy(expected), "raw_exceptions": 0,
                    "codec_failures": 0, "recovery_successes": 10},
        "resources": {}, "environment": {}, "limitations": [],
        "production_authorized": False, "verdict": "PASS",
    }


def test_resilience_report_accepts_only_exact_oracle():
    assert validate_report(valid_report()) == []
    report = valid_report()
    report["results"]["observed"]["success"] -= 1
    assert "DYN-ORACLE" in validate_report(report)


def test_resilience_report_rejects_raw_codec_recovery_and_authorization_failures():
    for field, failure in (
        ("raw_exceptions", "DYN-RAW-EXCEPTION"),
        ("codec_failures", "DYN-CODEC"),
        ("recovery_successes", "DYN-RECOVERY"),
    ):
        report = valid_report()
        report["results"][field] = 1
        assert failure in validate_report(report)
    report = valid_report()
    report["production_authorized"] = True
    assert "DYN-PRODUCTION-AUTHORIZATION" in validate_report(report)


def test_resilience_report_rejects_false_verdict_and_schema():
    report = valid_report()
    report["verdict"] = "FAIL"
    assert "DYN-VERDICT-CONTRADICTION" in validate_report(report)
    report = valid_report()
    report["schema"] = "unknown"
    assert "DYN-SCHEMA" in validate_report(report)
