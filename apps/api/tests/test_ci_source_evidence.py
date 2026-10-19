from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from korpus.application.operations import OperationalReleaseGate
from korpus.application.provenance import compute_source_digest

from scripts import current_truth_source as source
from scripts.check_mutation_report_freshness import catalogue_ids
from scripts.verify_ci_mirror import pipeline_invocations
from scripts.verify_current_truth import evaluate
from scripts.verify_gate_closure import parse_graph

ROOT = Path(__file__).resolve().parents[3]


def _write(root: Path, relative: str, payload: dict) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _source_fixture(root: Path) -> None:
    aliases = (
        "RELEASE_ENVELOPE.json",
        "CANONICAL_RELEASE_REPORT.json",
        "reports/CANONICAL_RELEASE_REPORT.json",
        "FULL_SSOT_PACKAGE_RECEIPT.json",
        "PACKAGE_BUILD.json",
        "GITHUB_IMPORT.md",
        "GITLAB_IMPORT.md",
        "apps/api/src/korpus/release.json",
        "config/operations/reference-v5.json",
        "config/operations/admission-grounds.json",
    )
    for relative in aliases:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    digest = compute_source_digest(root)
    ids = sorted(catalogue_ids())
    reports = {
        "eval": {
            "pass_rate": 1.0,
            "citation_failures": 0,
            "leakage_failures": 0,
            "leakage_checks": 26,
            "determinism_failures": 0,
            "audit_valid": True,
        },
        "mutation": {
            "mutation_score": 1.0,
            "mutants": len(ids),
            "killed": len(ids),
            "survived": [],
            "invalid": [],
            "errors": [],
            "results": [{"id": name, "status": "KILLED"} for name in ids],
        },
        "migration": {
            "table_set_match": True,
            "audit_head_seeded": True,
            "sqlite_fts5_present": True,
            "tables_actual": [
                "audit_anchor_outbox",
                "audit_events",
                "audit_heads",
                "document_compartments",
                "documents",
                "document_versions",
                "evidence_spans",
                "ingestion_jobs",
                "span_embeddings",
            ],
        },
        "scale": {
            "status": "PASS",
            "metric_status": "ANCHORED_LOCAL_MEASUREMENT",
            "results": {
                "top1_recall": 1.0,
                "candidate_count": 256,
                "query_latency_ms_p95": 49.9,
            },
        },
    }
    for name, payload in reports.items():
        payload["provenance"] = {
            "schema_version": 1,
            "source_digest": digest,
            "generator": "negative-control-fixture",
            "generated_at": "2026-10-19T00:00:00+00:00",
        }
        _write(root, source.REPORT_PATHS[name], payload)
    paths = {name: root / relative for name, relative in source.REPORT_PATHS.items()}
    gate = OperationalReleaseGate.load(root / "config/operations/reference-v5.json").evaluate(
        reports, paths, source_digest=digest
    )
    assert gate.passed
    _write(root, "var/operational-gate.json", gate.as_dict())
    for relative in source.STATIC_REPORTS:
        _write(
            root,
            relative,
            {
                "status": "PASS",
                "release": "v0.9.7",
                "source_tree_sha256": digest,
                "digest_scope": "evidence_paths",
            },
        )
    _write(
        root,
        "reports/MUTATION_REPORT.json",
        {"historical": True, "source_digest": "old"},
    )


def test_source_context_uses_current_run_without_relabelling_history(
    tmp_path: Path,
) -> None:
    _source_fixture(tmp_path)
    frozen = (tmp_path / "reports/MUTATION_REPORT.json").read_bytes()
    result = source.evaluate_source(tmp_path)
    assert result["status"] == "PASS", result
    assert result["production_authorized"] is False
    assert (tmp_path / "reports/MUTATION_REPORT.json").read_bytes() == frozen
    assert evaluate(tmp_path)["status"] == "FAIL"


@pytest.mark.parametrize(
    "poison", ["stale", "catalogue", "failed", "forged", "malformed", "surface"]
)
def test_source_context_rejects_invalid_current_evidence(tmp_path: Path, poison: str) -> None:
    _source_fixture(tmp_path)
    if poison == "surface":
        _write(tmp_path, "var/production/inference_security-gate.json", {})
    elif poison == "malformed":
        (tmp_path / "var/eval-report.json").write_text("not-json", encoding="utf-8")
    else:
        relative = {
            "stale": "var/eval-report.json",
            "catalogue": "var/mutation-report.json",
            "failed": "var/scale-report.json",
            "forged": "var/operational-gate.json",
        }[poison]
        payload = json.loads((tmp_path / relative).read_text(encoding="utf-8"))
        if poison == "stale":
            payload["provenance"]["source_digest"] = "f" * 64
        elif poison == "catalogue":
            payload["results"][0]["id"] = "UNKNOWN_MUTANT"
        elif poison == "failed":
            payload["results"]["top1_recall"] = 0
        else:
            payload["checks"] = {"invented_pass": True}
        _write(tmp_path, relative, payload)
    assert source.evaluate_source(tmp_path)["status"] == "FAIL"


def test_context_defaults_and_make_overrides_remain_distinct_subjects() -> None:
    makefile = (
        "REPOSITORY_CONTEXT ?= FULL_SSOT_DISTRIBUTION\n"
        "validate:\n\tpython scripts/validate_repository.py --context $(REPOSITORY_CONTEXT)\n"
    )
    _, _, scripts = parse_graph(makefile)
    full = "scripts/validate_repository.py --context FULL_SSOT_DISTRIBUTION"
    checkout = "scripts/validate_repository.py --context SOURCE_CHECKOUT"
    assert scripts["validate"] == {full}
    pipeline = {"source": {"script": ["make validate REPOSITORY_CONTEXT=SOURCE_CHECKOUT"]}}
    invoked, _ = pipeline_invocations(pipeline, makefile)
    assert checkout in invoked
    assert full not in invoked
    pipeline["source"]["script"] = [
        "make validate REPOSITORY_CONTEXT=SOURCE_CHECKOUT; make validate"
    ]
    invoked, _ = pipeline_invocations(pipeline, makefile)
    assert {checkout, full} <= invoked.keys()


def test_repair_plan_includes_current_consumers_of_a_scheduled_change(
    monkeypatch, tmp_path: Path
) -> None:
    from scripts import check_evidence_freshness as checker

    _source_fixture(tmp_path)
    evaluation = json.loads((tmp_path / "var/eval-report.json").read_text())
    evaluation["provenance"]["source_digest"] = "f" * 64
    _write(tmp_path, "var/eval-report.json", evaluation)
    operational = json.loads((tmp_path / "var/operational-gate.json").read_text())
    operational["evidence_sha256"]["eval"] = hashlib.sha256(
        (tmp_path / "var/eval-report.json").read_bytes()
    ).hexdigest()
    _write(tmp_path, "var/operational-gate.json", operational)
    _write(
        tmp_path,
        "var/final.json",
        {
            "evidence_sha256": {
                "operational": hashlib.sha256(
                    (tmp_path / "var/operational-gate.json").read_bytes()
                ).hexdigest()
            }
        },
    )
    monkeypatch.setattr(
        checker,
        "CONSUMERS",
        (
            *checker.CONSUMERS,
            ("var/final.json", "final", {"operational": "var/operational-gate.json"}),
        ),
    )
    verdict = checker.evaluate(tmp_path)
    assert verdict["rerun_in_this_order"] == ["eval", "operational-gate", "final"]


def test_mutation_portable_opt_out_preserves_history_and_default(
    monkeypatch, tmp_path: Path
) -> None:
    import run_mutation_tests as runner

    args = SimpleNamespace(merge=True, portable=False, only="", shard_count=1, jobs=1)
    report = {"status": "PASS", "results": [{"id": "M1"}], "valid_mutants": 1}
    for name in ("MUTATION_REPORT.json", "MUTATION_FULL_CATALOGUE_CURRENT.json"):
        _write(tmp_path, "reports/" + name, {"historical": True})
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "MUTANTS", [object()])
    monkeypatch.setattr(runner, "parse_args", lambda: args)
    monkeypatch.setattr(
        runner,
        "_run_catalogue",
        lambda _: (report, tmp_path / "var/mutation-report.json"),
    )
    monkeypatch.setattr(runner, "_print_summary", lambda _: None)
    assert runner.main() == 0
    assert json.loads((tmp_path / "reports/MUTATION_REPORT.json").read_text()) == {
        "historical": True
    }
    assert json.loads((tmp_path / "var/mutation-report.json").read_text()) == report
    args.portable = True
    assert runner.main() == 0
    assert (tmp_path / "reports/MUTATION_REPORT.json").read_bytes() == (
        tmp_path / "var/mutation-report.json"
    ).read_bytes()


def test_mutation_checker_explicit_report_preserves_all_predicates(
    monkeypatch, tmp_path: Path
) -> None:
    from scripts import check_mutation_report_freshness as checker

    _source_fixture(tmp_path)
    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "REPORT", tmp_path / "reports/MUTATION_REPORT.json")
    monkeypatch.setattr(sys, "argv", ["checker", "--report", "var/mutation-report.json"])
    assert checker.main() == 0
    monkeypatch.setattr(sys, "argv", ["checker"])
    assert checker.main() == 1


def test_source_predicate_output_does_not_rewrite_release_report(
    monkeypatch, tmp_path: Path
) -> None:
    from scripts import verify_production_hard_predicates as gate

    _write(tmp_path, "reports/PRODUCTION_HARD_PREDICATES.json", {"historical": True})
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "build", lambda: {"software_ready": 14, "predicates_total": 14})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gate",
            "--context",
            "SOURCE_CHECKOUT",
            "--out",
            "var/source-production-hard-predicates.json",
        ],
    )
    assert gate.main() == 0
    assert json.loads((tmp_path / "reports/PRODUCTION_HARD_PREDICATES.json").read_text()) == {
        "historical": True
    }
    assert (tmp_path / "var/source-production-hard-predicates.json").is_file()
