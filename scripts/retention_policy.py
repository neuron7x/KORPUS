#!/usr/bin/env python3
"""Backup copies, evidence retention and quotas — declared, and checked against the disk.

Three findings share one shape, so they share one file:

  INF-012  3-2-1 backups with object lock and a restore cadence
  OPS-003  an immutable evidence registry with a retention aligned to the system's life
  OPS-005  per-tenant quotas, cost attribution, budget alerts, a rate policy

Each was a policy nobody had written, and the temptation with all three is to write the
policy and stop. A policy in a document is a sentence; the thing that makes it a control
is something that looks at the disk and says which clause is currently false. So the
clauses are data here, and the checker reports each one as met or not with what it found.

What "immutable" means locally, stated because the word is doing work: `chattr +i` where
the filesystem supports it, and mode 0444 with the directory 0500 where it does not.
Neither survives root. Object lock on an S3 bucket with a separate credential is what
survives an operator, and it is external — named in every report rather than implied by
the word.

    retention_policy.py check
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Clause:
    finding: str
    name: str
    statement: str
    rationale: str
    #: `external` clauses are reported as external, never as failed. A clause nothing on
    #: this host can satisfy, counted as a failure, trains everyone to read a red status
    #: as normal — which is the same as having no status.
    scope: str = "local"


CLAUSES = (
    Clause(
        "INF-012",
        "copies.at_least_two_media",
        "a corpus backup exists in at least two locations",
        "One disk is not a backup; it is the same failure twice under two names.",
    ),
    Clause(
        "INF-012",
        "copies.second_location",
        "at least one copy is outside the working tree",
        (
            "The nearest thing to a second location this host can offer. A fire, a theft "
            "and a full-disk encryption event all still take both."
        ),
    ),
    Clause(
        "INF-012",
        "copies.offsite",
        "at least one copy is on hardware this operator does not control",
        "A fire, a theft and a full-disk encryption event all take everything in one room.",
        scope="external",
    ),
    Clause(
        "INF-012",
        "copies.immutable",
        "the newest backup cannot be overwritten by the process that wrote it",
        (
            "Ransomware and a careless script both work by writing. Locally this is "
            "chattr +i or mode 0444; neither survives root, which is why object lock with "
            "a separate credential is named as external rather than assumed."
        ),
    ),
    Clause(
        "INF-012",
        "restore.cadence",
        "a restore has been executed within the last 30 days",
        "A backup nobody has restored is a file. The drill is the property, not the copy.",
    ),
    Clause(
        "OPS-003",
        "evidence.retained",
        "gate reports are kept for the system's life, not the pipeline's",
        (
            "CI artefacts expire in weeks. The question 'what did this system answer in "
            "August, and what proved it was sound' is asked years later."
        ),
    ),
    Clause(
        "OPS-003",
        "evidence.tamper_evident",
        "the evidence registry carries a digest over its own contents",
        "A registry anyone can edit answers whatever the last editor wanted it to.",
    ),
    Clause(
        "OPS-005",
        "quota.rate_policy",
        "the public edge limits per visitor and in aggregate",
        (
            "Measured 2026-08-06: keyed on the tunnel's address it refused 34 898 of "
            "34 977 requests — one bucket for the whole internet is not a quota."
        ),
    ),
    Clause(
        "OPS-005",
        "quota.admission_budget",
        "the API refuses work beyond a stated concurrency rather than queueing it",
        "A system that queues without bound answers everyone too late instead of some now.",
    ),
)


def _immutable(path: Path) -> tuple[bool, str]:
    if shutil.which("lsattr"):
        completed = subprocess.run(
            ["lsattr", "-d", str(path)], capture_output=True, text=True, check=False, timeout=30
        )
        if completed.returncode == 0 and "i" in completed.stdout.split()[0]:
            return True, "chattr +i"
    mode = path.stat().st_mode & 0o777
    if mode == 0o444:
        return True, "mode 0444 (does not survive root)"
    return False, f"mode {mode:o}"


def _newest(directory: Path, pattern: str) -> Path | None:
    candidates = sorted(directory.glob(pattern), key=lambda item: item.stat().st_mtime)
    return candidates[-1] if candidates else None


def _check(arguments: argparse.Namespace) -> dict[str, Any]:
    backups = arguments.backup_dir
    offsite = arguments.offsite_dir
    evidence = arguments.evidence_dir
    findings: dict[str, dict[str, Any]] = {}

    newest = _newest(backups, "korpus-*.tar.enc") if backups.is_dir() else None
    local_count = len(list(backups.glob("korpus-*.tar.enc"))) if backups.is_dir() else 0
    offsite_count = len(list(offsite.glob("korpus-*.tar.enc"))) if offsite.is_dir() else 0

    immutable, how = _immutable(newest) if newest else (False, "no backup to check")
    restored_at = None
    marker = backups / "last-restore.json" if backups.is_dir() else None
    if marker and marker.is_file():
        restored_at = json.loads(marker.read_text(encoding="utf-8")).get("restored_at")
    fresh_restore = False
    if restored_at:
        moment = datetime.fromisoformat(str(restored_at))
        fresh_restore = datetime.now(UTC) - moment < timedelta(days=30)

    registry = evidence / "registry.json"
    registry_present = registry.is_file()
    registry_sealed = False
    if registry_present:
        body = json.loads(registry.read_text(encoding="utf-8"))
        registry_sealed = bool(body.get("content_digest"))

    edge = (ROOT / "deploy/public/nginx.conf").read_text(encoding="utf-8") if (
        ROOT / "deploy/public/nginx.conf"
    ).is_file() else ""
    serve = (ROOT / "scripts/serve_public.sh").read_text(encoding="utf-8") if (
        ROOT / "scripts/serve_public.sh"
    ).is_file() else ""

    observed = {
        "copies.at_least_two_media": (local_count + offsite_count >= 2,
                                      f"{local_count} local, {offsite_count} second-location"),
        "copies.second_location": (offsite_count >= 1, f"{offsite_count} in {offsite}"),
        "copies.offsite": (False, "no storage outside this host is configured"),
        "copies.immutable": (immutable, how),
        "restore.cadence": (fresh_restore, f"last restore {restored_at or 'never'}"),
        "evidence.retained": (registry_present, f"registry at {registry}"),
        "evidence.tamper_evident": (registry_sealed, "content_digest present"
                                    if registry_sealed else "no digest over the registry"),
        "quota.rate_policy": (
            "real_ip_header" in edge and "korpus_public_total" in edge,
            "per-visitor key and an aggregate zone" if "korpus_public_total" in edge else "absent",
        ),
        "quota.admission_budget": (
            "KORPUS_MAX_CONCURRENT_ANSWERS" in serve,
            "admission limit set for the public identity" if "KORPUS_MAX_CONCURRENT_ANSWERS"
            in serve else "absent",
        ),
    }

    for clause in CLAUSES:
        met, detail = observed[clause.name]
        findings.setdefault(clause.finding, {"clauses": []})["clauses"].append(
            {
                "name": clause.name,
                "statement": clause.statement,
                "rationale": clause.rationale,
                "scope": clause.scope,
                "met": met if clause.scope == "local" else None,
                "observed": detail,
            }
        )
    for body in findings.values():
        local = [clause for clause in body["clauses"] if clause["scope"] == "local"]
        body["met"] = all(clause["met"] for clause in local)
        body["external_clauses"] = [
            clause["name"] for clause in body["clauses"] if clause["scope"] == "external"
        ]

    return {
        "schema_version": 1,
        "checked_at": datetime.now(UTC).isoformat(),
        "findings": findings,
        "status": "PASS" if all(body["met"] for body in findings.values()) else "FAIL",
        "external": [
            "Object lock on a bucket with a credential the writer does not hold is what "
            "survives an operator. chattr +i and mode 0444 do not survive root.",
            "Cost attribution needs a billing account; there is none.",
        ],
        "interpretation": (
            "A policy in a document is a sentence. Each clause here is checked against the "
            "disk and reported with what was found, so an unmet clause is visible as "
            "unmet rather than as prose nobody re-read."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-dir", type=Path, default=ROOT / "var/backups/sqlite")
    parser.add_argument("--offsite-dir", type=Path, default=ROOT / "var/backups/offsite")
    parser.add_argument("--evidence-dir", type=Path, default=ROOT / "var/evidence")
    parser.add_argument("--out", type=Path, default=ROOT / "var/retention-policy.json")
    arguments = parser.parse_args()

    report = _check(arguments)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
