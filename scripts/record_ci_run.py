#!/usr/bin/env python3
"""Record required GitHub Actions checks for one exact candidate commit SHA."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_ci_mirror import mandatory_workflow_jobs  # noqa: E402


@dataclass(frozen=True)
class JobCatalogue:
    required: tuple[str, ...] = ()
    mandatory: tuple[str, ...] = ()
    excused: frozenset[str] = frozenset()


def candidate_ci() -> dict[str, Any]:
    payload = json.loads((ROOT / "RELEASE_ENVELOPE.json").read_text(encoding="utf-8"))
    candidate = payload.get("release_candidate")
    ci = candidate.get("ci") if isinstance(candidate, dict) else None
    return ci if isinstance(ci, dict) else {}


def catalogue(ci: dict[str, Any], *, root: Path = ROOT) -> JobCatalogue:
    names: list[str] = []
    for raw in ci.get("mandatory_pr_workflows") or ():
        relative = Path(str(raw))
        if relative.is_absolute() or ".." in relative.parts:
            continue
        try:
            workflow = yaml.safe_load((root / relative).read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(workflow, dict):
            names.extend(mandatory_workflow_jobs(workflow))
    return JobCatalogue(
        tuple(str(name) for name in ci.get("required_jobs") or ()),
        tuple(sorted(set(names))),
        frozenset(str(name) for name in ci.get("jobs_not_required") or ()),
    )


def head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip().lower()


def github_check_runs(repository: str, commit: str) -> dict[str, Any] | None:
    result = subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "GET",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            "X-GitHub-Api-Version: 2022-11-28",
            f"repos/{repository}/commits/{commit}/check-runs?filter=latest&per_page=100",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("check_runs"), list):
        return None
    total = payload.get("total_count")
    return None if isinstance(total, int) and total > len(payload["check_runs"]) else payload


def _latest_actions_checks(commit: str, payload: Any) -> dict[str, dict[str, Any]] | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("check_runs"), list):
        return None
    latest: dict[str, dict[str, Any]] = {}
    for raw in payload["check_runs"]:
        if not isinstance(raw, dict) or str(raw.get("head_sha") or "").lower() != commit:
            continue
        app = raw.get("app")
        if not isinstance(app, dict) or app.get("slug") != "github-actions":
            continue
        name = str(raw.get("name") or "")
        old = latest.get(name)
        old_id = old.get("id", -1) if old else -1
        new_id = raw.get("id", -1)
        if name and isinstance(old_id, int) and isinstance(new_id, int) and new_id >= old_id:
            latest[name] = raw
    return latest


def _base_report(commit: str, required: tuple[str, ...], url: str) -> dict[str, Any]:
    return {
        "schema": "korpus.ci-run.v2",
        "provider": "github-actions",
        "commit": commit,
        "required_jobs": sorted(required),
        "completed_jobs": [],
        "failed_jobs": [],
        "pipeline": url,
        "ran_at": datetime.now(UTC).isoformat(),
    }


def _stop(report: dict[str, Any], status: str, detail: str) -> dict[str, Any]:
    report.update(status=status, detail=detail)
    return report


def _catalogue_drift(jobs: JobCatalogue) -> tuple[list[str], list[str]]:
    expected = set(jobs.mandatory) - set(jobs.excused)
    required = set(jobs.required)
    return sorted(required - expected), sorted(expected - required)


def adjudicate(
    commit: str, jobs: JobCatalogue, payload: Any, *, checks_url: str = ""
) -> dict[str, Any]:
    report = _base_report(commit, jobs.required, checks_url)
    if not _FULL_SHA.fullmatch(commit):
        return _stop(report, "NOT_MEASURED", "кандидат не є повним commit SHA")
    if not jobs.required:
        return _stop(report, "NOT_MEASURED", "конверт не називає required checks")
    undeclared, unrequired = _catalogue_drift(jobs)
    report.update(
        required_not_in_workflows=undeclared,
        workflow_jobs_not_required=unrequired,
    )
    if undeclared or unrequired:
        return _stop(
            report,
            "FAIL",
            f"конверт не збігається з workflow jobs: {undeclared=}, {unrequired=}",
        )
    latest = _latest_actions_checks(commit, payload)
    if latest is None:
        return _stop(report, "NOT_MEASURED", "check-runs API не дав валідної відповіді")
    if not latest:
        return _stop(report, "NOT_MEASURED", "для точного SHA немає GitHub Actions checks")
    required = set(jobs.required)
    missing = sorted(required - set(latest))
    failed = sorted(
        name
        for name in required & set(latest)
        if (latest[name].get("status"), latest[name].get("conclusion")) != ("completed", "success")
    )
    report.update(
        completed_jobs=sorted(required - set(missing) - set(failed)),
        failed_jobs=failed,
        missing_jobs=missing,
    )
    if missing:
        return _stop(report, "FAIL", f"required checks відсутні: {missing}")
    if failed:
        return _stop(report, "FAIL", f"required checks неуспішні: {failed}")
    return _stop(report, "PASS", "усі required jobs успішні на точному commit SHA")


def _check(
    name: str,
    commit: str,
    conclusion: Any = "success",
    status: str = "completed",
    check_id: int = 1,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "name": name,
        "head_sha": commit,
        "status": status,
        "conclusion": conclusion,
        "app": {"slug": "github-actions"},
    }


def selftest() -> int:
    commit = "c" * 40
    required = ("a", "b")
    jobs = JobCatalogue(required, required)

    def judge(payload: Any, catalogue_: JobCatalogue = jobs, sha: str = commit) -> str:
        return str(adjudicate(sha, catalogue_, payload)["status"])

    good = [_check("a", commit), _check("b", commit, check_id=2)]
    foreign = [_check("a", commit), _check("b", "d" * 40)]
    other_app = _check("b", commit) | {"app": {"slug": "other-ci"}}
    cases: list[tuple[str, Any, Any]] = [
        ("API absent", judge(None), "NOT_MEASURED"),
        ("zero checks", judge({"check_runs": []}), "NOT_MEASURED"),
        ("ref is not exact SHA", judge({"check_runs": []}, sha="main"), "NOT_MEASURED"),
        (
            "empty denominator",
            judge({"check_runs": good}, JobCatalogue()),
            "NOT_MEASURED",
        ),
        ("all required success", judge({"check_runs": good}), "PASS"),
        ("missing required", judge({"check_runs": good[:1]}), "FAIL"),
        (
            "skipped required",
            judge({"check_runs": [good[0], _check("b", commit, "skipped")]}),
            "FAIL",
        ),
        (
            "queued required",
            judge({"check_runs": [good[0], _check("b", commit, None, "queued")]}),
            "FAIL",
        ),
        (
            "failed required",
            judge({"check_runs": [good[0], _check("b", commit, "failure")]}),
            "FAIL",
        ),
        ("foreign SHA", judge({"check_runs": foreign}), "FAIL"),
        ("foreign app", judge({"check_runs": [good[0], other_app]}), "FAIL"),
        (
            "new mandatory job",
            judge({"check_runs": good}, JobCatalogue(required, ("a", "b", "c"))),
            "FAIL",
        ),
        (
            "required name outside workflow",
            judge({"check_runs": good}, JobCatalogue(("a", "b"), ("a",))),
            "FAIL",
        ),
        (
            "latest rerun governs",
            judge(
                {"check_runs": [_check("a", commit, "failure"), _check("a", commit, check_id=2)]},
                JobCatalogue(("a",), ("a",)),
            ),
            "PASS",
        ),
        (
            "conditional jobs excluded",
            mandatory_workflow_jobs(
                {
                    "jobs": {
                        "a": {"name": "A"},
                        "b": {"name": "B", "if": "false"},
                        "c": {"name": "C", "continue-on-error": True},
                    }
                }
            ),
            ["A"],
        ),
    ]
    passed = sum(got == want for _name, got, want in cases)
    for name, got, want in cases:
        print(f"  {'ok' if got == want else 'FAIL'} {name}: {got!r}")
    print(f"negative controls: {passed}/{len(cases)}")
    return 0 if passed == len(cases) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="")
    parser.add_argument("--out", type=Path, default=ROOT / "var/ci-run.json")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--evidence-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    ci = candidate_ci()
    commit = (arguments.commit or head()).lower()
    repository = str(ci.get("repository") or "")
    payload = (
        github_check_runs(repository, commit)
        if repository and _FULL_SHA.fullmatch(commit)
        else None
    )
    url = f"https://github.com/{repository}/commit/{commit}/checks" if repository else ""
    report = adjudicate(commit, catalogue(ci), payload, checks_url=url)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    arguments.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if arguments.evidence_only or report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
