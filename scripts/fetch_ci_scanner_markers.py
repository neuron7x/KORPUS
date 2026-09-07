#!/usr/bin/env python3
"""Маркери сканерів із конвеєра — у `var/security/`, з перевіркою коміта.

Предикат `live_vulnerability_scanners` читає `var/security/ci-*.json` і питає, чи
`commit_sha` кожного маркера лежить у множині комітів із ТОТОЖНИМ джерелом. Доти
єдиним виробником цих файлів була рука: хтось відкривав конвеєр, качав артефакт і
клав його в дерево. Різниця між «сканер відпрацював на цьому коді» і «файл про це є»
була невидима за побудовою — той самий клас, що й у чистої кімнати до появи
`reproduce_clean_room.py`.

Що робить цей скрипт і чого НЕ робить. Він качає артефакти названих джобів і кладе
їх на місце ЛИШЕ якщо `commit_sha` маркера прийнятний для цього дерева. Він не
вигадує маркерів, не редагує їх і не приймає рішення про предикат — вирок лишається
за `verify_production_hard_predicates`.

    fetch_ci_scanner_markers.py --pipeline 2827708067
    fetch_ci_scanner_markers.py --pipeline 2827708067 --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from source_digest import commits_with_identical_source  # noqa: E402

PROJECT = "neuron7x%2Fkorpus-platform"
OUT = ROOT / "var/security"

#: Джоб -> файл, який він кладе. Перелік ЗАКРИТИЙ: новий сканер мусить бути названий
#: тут, інакше його маркер не з'явиться сам, і предикат скаже про це прямо.
MARKERS = {
    "secret:scan": "ci-gitleaks.json",
    "python:audit": "ci-pip-audit.json",
    "container:scan": "ci-container-scan.json",
    "security:summary": "summary.json",
}


def _glab(*args: str) -> str:
    result = subprocess.run(["glab", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"glab {' '.join(args)}: {result.stderr.strip()[:200]}")
    return result.stdout


def pipeline_jobs(pipeline: str) -> list[dict[str, Any]]:
    raw = _glab("api", f"projects/{PROJECT}/pipelines/{pipeline}/jobs?per_page=100")
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise SystemExit("несподівана відповідь API: очікувався перелік джобів")
    return payload


def artifact(job_id: int, name: str) -> bytes | None:
    """Один файл із артефактів джоба, або None, якщо його там немає."""
    result = subprocess.run(
        ["glab", "api", f"projects/{PROJECT}/jobs/{job_id}/artifacts/var/security/{name}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 and result.stdout else None


def verdict(jobs: list[dict[str, Any]], accepted: frozenset[str]) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema": "korpus.ci-scanner-marker-fetch.v1",
        "accepted_commits": sorted(accepted),
        "fetched": {},
        "refused": {},
    }
    by_name = {job["name"]: job for job in jobs}
    for job_name, file_name in MARKERS.items():
        job = by_name.get(job_name)
        if job is None:
            report["refused"][file_name] = f"джоба {job_name} немає в конвеєрі"
            continue
        if job["status"] != "success":
            report["refused"][file_name] = f"{job_name}: {job['status']}"
            continue
        sha = str(job["commit"]["id"])
        if sha not in accepted:
            report["refused"][file_name] = (
                f"{job_name} біг на {sha[:12]}, а це не коміт із тотожним джерелом"
            )
            continue
        report["fetched"][file_name] = {"job": job_name, "job_id": job["id"], "commit": sha}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipeline", required=True)
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args()

    accepted = frozenset(commits_with_identical_source())
    if not accepted:
        raise SystemExit("порожня множина прийнятних комітів — маркер прийняти нема до чого")
    report = verdict(pipeline_jobs(arguments.pipeline), accepted)

    written: list[str] = []
    if not arguments.dry_run:
        OUT.mkdir(parents=True, exist_ok=True)
        for file_name, meta in list(report["fetched"].items()):
            payload = artifact(int(meta["job_id"]), file_name)
            if payload is None:
                report["refused"][file_name] = f"{meta['job']}: артефакта немає"
                del report["fetched"][file_name]
                continue
            (OUT / file_name).write_bytes(payload)
            written.append(file_name)
    report["written"] = written
    report["status"] = "PASS" if report["fetched"] and not report["refused"] else "PARTIAL"
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
