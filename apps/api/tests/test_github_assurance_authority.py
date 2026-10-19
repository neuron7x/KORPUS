from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
ASSURANCE = ROOT / ".github/workflows/assurance.yml"
CI = ROOT / ".github/workflows/ci.yml"


def _jobs() -> dict[str, dict]:
    document = yaml.safe_load(ASSURANCE.read_text(encoding="utf-8"))
    return document["jobs"]


def _runs(job: dict) -> str:
    return "\n".join(
        str(step["run"])
        for step in job.get("steps", ())
        if isinstance(step, dict) and "run" in step
    )


def _artifact_names(job: dict, action: str) -> set[str]:
    return {
        str(step.get("with", {}).get("name"))
        for step in job.get("steps", ())
        if isinstance(step, dict) and str(step.get("uses", "")).startswith(action)
    }


def test_source_scanners_are_independent_blockers_and_summary_consumes_their_artifacts() -> None:
    jobs = _jobs()
    producers = {
        "source-secret-scan": "security-gitleaks",
        "python-dependency-audit": "security-pip-audit",
        "infrastructure-scan": "security-trivy",
    }
    for job_id, artifact in producers.items():
        assert not jobs[job_id].get("needs")
        assert artifact in _artifact_names(jobs[job_id], "actions/upload-artifact@")

    summary = jobs["security-summary"]
    assert set(summary["needs"]) == set(producers)
    assert set(producers.values()) <= _artifact_names(summary, "actions/download-artifact@")
    assert '--commit "$GITHUB_SHA"' in _runs(summary)


def test_audit_closure_downloads_each_runtime_evidence_class_before_resolving() -> None:
    jobs = _jobs()
    closure = jobs["audit-closure"]
    assert set(closure["needs"]) == {
        "research-assurance",
        "assurance-drills",
        "security-summary",
    }
    assert _artifact_names(closure, "actions/download-artifact@") == {
        "research-assurance-evidence",
        "assurance-drill-evidence",
        "security-summary",
    }
    assert "scripts/build_audit_closure.py" in _runs(closure)


def test_container_scan_and_sbom_consume_the_same_candidate_images() -> None:
    jobs = _jobs()
    assert jobs["container-scan"]["needs"] == ["container-build"]
    assert jobs["container-sbom"]["needs"] == ["container-build"]
    for name in ("container-scan", "container-sbom"):
        assert "candidate-images" in _artifact_names(jobs[name], "actions/download-artifact@")


def test_sbom_jobs_emit_subject_receipts_with_their_payloads() -> None:
    jobs = _jobs()
    source = _runs(jobs["source-sbom"])
    containers = _runs(jobs["container-sbom"])
    assert "build_ci_evidence_receipt.py source-sbom" in source
    assert "var/source-sbom-receipt.json" in str(jobs["source-sbom"])
    assert "build_ci_evidence_receipt.py container-sboms" in containers
    assert "container-sbom-receipt.json" in str(jobs["container-sbom"])


def test_every_external_scanner_image_is_digest_pinned() -> None:
    runs = "\n".join(_runs(job) for job in _jobs().values())
    images = re.findall(r"(?:zricethezav/gitleaks|aquasec/trivy|anchore/syft):[^\s'\"]+", runs)
    assert len(images) >= 4
    assert all(re.search(r"@sha256:[0-9a-f]{64}$", image) for image in images)


def test_pip_audit_toolchain_is_hash_locked_and_mutable_install_is_absent() -> None:
    run = _runs(_jobs()["python-dependency-audit"])
    installs = [line.strip() for line in run.splitlines() if "pip install" in line]
    assert installs == [
        "python -m pip install --require-hashes --no-deps "
        "-r config/operations/pip-audit-toolchain.lock"
    ]
    lock = (ROOT / "config/operations/pip-audit-toolchain.lock").read_text(encoding="utf-8")
    records = [part for part in re.sub(r"\\\n\s*", " ", lock).splitlines() if "==" in part]
    assert any(line.startswith("pip-audit==2.10.1 ") for line in records)
    assert all(re.search(r"--hash=sha256:[0-9a-f]{64}(?:\s|$)", line) for line in records)


def test_blocking_container_scans_never_blanket_ignore_unfixed_findings() -> None:
    lines = [
        line.strip()
        for line in _runs(_jobs()["container-scan"]).splitlines()
        if "image --input" in line and "--exit-code 1" in line
    ]
    assert len(lines) == 2
    assert all("--ignore-unfixed" not in line for line in lines)
    assert "--ignorefile" not in next(line for line in lines if "api-image.tar" in line)
    web = next(line for line in lines if "web-image.tar" in line)
    assert "--ignorefile /work/.trivyignore.web.yaml" in web


def test_both_dialects_feed_one_fail_closed_union_job() -> None:
    jobs = _jobs()
    union = jobs["coverage-union"]
    assert set(union["needs"]) == {"sqlite-coverage", "postgres"}
    assert _artifact_names(union, "actions/download-artifact@") == {
        "sqlite-coverage-evidence",
        "postgres-evidence",
    }
    assert "merge_dialect_coverage.py" in _runs(union)
    assert "stamp_coverage_report.py" in _runs(jobs["sqlite-coverage"])
    assert "stamp_coverage_report.py" in _runs(jobs["postgres"])
    assert "build_ci_evidence_receipt.py coverage-union" in _runs(union)
    assert "coverage-ci-receipt.json" in str(union)


def test_assurance_importer_is_the_make_entrypoint_for_sbom_and_coverage() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("ci-assurance-evidence:", 1)[1].split("\n\n", 1)[0]
    assert "fetch_ci_assurance_evidence.py" in recipe
    assert '--run "$(RUN)"' in recipe


def test_previously_unmirrored_lane_commands_are_blocking() -> None:
    jobs = _jobs()
    assert "scripts/run_plasticity_gate.py" in _runs(jobs["research-assurance"])
    assert "scripts/chaos_matrix.py" in _runs(jobs["assurance-drills"])

    ci_jobs = yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]
    web = _runs(ci_jobs["web-test"])
    assert "make web-contract-check PY=python" in web


def test_uploaded_evidence_is_replaced_by_the_current_run_attempt() -> None:
    workflows = (_jobs(), yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"])
    uploads = [
        step
        for jobs in workflows
        for job in jobs.values()
        for step in job.get("steps", ())
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert uploads
    assert all(step.get("with", {}).get("overwrite") is True for step in uploads)
