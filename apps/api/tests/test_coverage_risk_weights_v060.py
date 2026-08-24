from __future__ import annotations

from scripts.coverage_gap_plan import build_plan


def _coverage() -> dict:
    def item(missing: int) -> dict:
        return {"summary": {"missing_branches": missing, "percent_branches_covered": 50.0}}
    return {
        "totals": {
            "covered_lines": 96, "num_statements": 100,
            "covered_branches": 92, "num_branches": 100, "missing_branches": 8,
        },
        "files": {
            "apps/api/src/korpus/security/auth.py": item(2),
            "apps/api/src/korpus/infrastructure/repository.py": item(3),
            "apps/api/src/korpus/application/cache.py": item(3),
        },
    }


def test_risk_weights_are_applied_after_canonical_source_path_normalization(tmp_path) -> None:
    policy = {
        "coverage": {
            "minimum_statement_rate": 0.95,
            "minimum_branch_rate": 0.90,
            "baseline_missing_branches": 8,
            "maximum_missing_branch_regression": 0,
        },
        "risk_weights": {"security/": 5.0, "infrastructure/": 3.0, "application/": 2.0},
    }
    queue = build_plan(_coverage(), policy, tmp_path)["priority_queue"]
    by_path = {item["path"]: item for item in queue}
    assert by_path["security/auth.py"]["risk_weight"] == 5.0
    assert by_path["infrastructure/repository.py"]["risk_weight"] == 3.0
    assert by_path["application/cache.py"]["risk_weight"] == 2.0
    assert queue[0]["path"] == "security/auth.py"


def test_absolute_source_paths_receive_the_same_risk_weight(tmp_path) -> None:
    coverage = _coverage()
    coverage["files"] = {
        "/tmp/work/apps/api/src/korpus/security/auth.py": coverage["files"].pop(
            "apps/api/src/korpus/security/auth.py"
        )
    }
    policy = {
        "coverage": {
            "minimum_statement_rate": 0.95, "minimum_branch_rate": 0.90,
            "baseline_missing_branches": 8, "maximum_missing_branch_regression": 0,
        },
        "risk_weights": {"security/": 5.0},
    }
    item = build_plan(coverage, policy, tmp_path)["priority_queue"][0]
    assert item["path"] == "security/auth.py"
    assert item["risk_weight"] == 5.0
