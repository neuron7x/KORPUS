#!/usr/bin/env python3
"""How long a known vulnerability may stay in this tree, and whether it has.

SUP-008. The pipeline scans; nothing said what a finding obliges anyone to do, or by when,
or what happens if the scan itself stops running. A scanner with no deadline attached
produces a list that is read once.

Three clauses, each checked rather than declared:

  freshness   a scan older than the interval is not a pass. The most common way a
              dependency policy fails is that the scan quietly stopped running and the
              last green report kept being the answer.
  severity    CRITICAL and HIGH carry deadlines. A deadline nobody measures against a
              clock is a preference.
  known-exploited
              anything on CISA's KEV list is due immediately, whatever its CVSS. A
              vulnerability being exploited in the wild is not a scoring question, and
              KEV is the only input here that comes from outside — which is why its
              absence is reported as unknown rather than as clean.

The KEV catalogue is not fetched. This tree does not reach the internet at scan time by
design — the parser must never have a reason to — so the catalogue is a file an operator
refreshes, and if it is missing every finding is reported as `kev_unknown` rather than as
not-exploited. Assuming absence from a list nobody loaded is the failure this whole
project is about.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

#: Days from the scan that first saw it. Chosen to be survivable rather than aspirational:
#: a deadline nobody can meet is missed once and then ignored.
SLA_DAYS = {"CRITICAL": 7, "HIGH": 30, "MEDIUM": 90, "LOW": 180}

#: Immediately, whatever the score.
KEV_SLA_DAYS = 0

#: A scan older than this is not evidence about today.
MAX_SCAN_AGE_DAYS = 7


@dataclass(frozen=True)
class Finding:
    identifier: str
    severity: str
    component: str
    source: str


def _from_trivy(path: Path) -> list[Finding]:
    if not path.is_file():
        return []
    body = json.loads(path.read_text(encoding="utf-8"))
    findings: list[Finding] = []
    for result in body.get("Results") or []:
        for vulnerability in result.get("Vulnerabilities") or []:
            findings.append(
                Finding(
                    identifier=str(vulnerability.get("VulnerabilityID", "")),
                    severity=str(vulnerability.get("Severity", "UNKNOWN")).upper(),
                    component=str(vulnerability.get("PkgName", "")),
                    source="trivy",
                )
            )
    return findings


def _from_pip_audit(path: Path) -> list[Finding]:
    if not path.is_file():
        return []
    body = json.loads(path.read_text(encoding="utf-8"))
    findings: list[Finding] = []
    for dependency in body.get("dependencies") or []:
        for vulnerability in dependency.get("vulns") or []:
            findings.append(
                Finding(
                    identifier=str(vulnerability.get("id", "")),
                    # pip-audit does not grade. Reported as UNKNOWN and given the strictest
                    # deadline rather than the loosest: an ungraded finding is not a mild
                    # one, it is one nobody has looked at.
                    severity="UNKNOWN",
                    component=str(dependency.get("name", "")),
                    source="pip-audit",
                )
            )
    return findings


def _kev(path: Path) -> tuple[set[str], str]:
    if not path.is_file():
        return set(), "absent"
    body = json.loads(path.read_text(encoding="utf-8"))
    entries = body.get("vulnerabilities") or []
    return {str(entry.get("cveID", "")) for entry in entries}, str(
        body.get("catalogVersion") or body.get("dateReleased") or "unknown"
    )


def _due(finding: Finding, seen_at: datetime, kev: set[str], kev_state: str) -> dict[str, Any]:
    if kev_state == "absent":
        obligation, days = "kev_unknown", SLA_DAYS.get(finding.severity, 7)
    elif finding.identifier in kev:
        obligation, days = "known_exploited", KEV_SLA_DAYS
    else:
        obligation, days = "graded", SLA_DAYS.get(finding.severity, 7)
    due = seen_at + timedelta(days=days)
    return {
        "id": finding.identifier,
        "severity": finding.severity,
        "component": finding.component,
        "source": finding.source,
        "obligation": obligation,
        "due_at": due.isoformat(),
        "overdue": datetime.now(UTC) > due,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", type=Path, default=ROOT / "var/security")
    parser.add_argument("--kev", type=Path, default=ROOT / "config/operations/kev-catalogue.json")
    parser.add_argument("--out", type=Path, default=ROOT / "var/patch-policy.json")
    arguments = parser.parse_args()

    summary_path = arguments.reports / "summary.json"
    if not summary_path.is_file():
        print(
            json.dumps(
                {
                    "status": "UNSCANNED",
                    "reason": f"no scanner summary at {summary_path}",
                    "interpretation": (
                        "Not a pass. A policy about findings, run where no scan has "
                        "happened, has established nothing about this tree."
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    scanned_at = datetime.fromisoformat(str(summary["ran_at"]))
    age = datetime.now(UTC) - scanned_at
    stale = age > timedelta(days=MAX_SCAN_AGE_DAYS)

    kev, kev_state = _kev(arguments.kev)
    findings = [
        *_from_trivy(arguments.reports / "trivy-fs.json"),
        *_from_pip_audit(arguments.reports / "pip-audit-runtime.json"),
        *_from_pip_audit(arguments.reports / "pip-audit-dev.json"),
    ]
    obligations = [_due(finding, scanned_at, kev, kev_state) for finding in findings]
    overdue = [item for item in obligations if item["overdue"]]
    unexecuted = [
        item["scanner"] for item in summary.get("scanners", []) if item.get("exit_code") == 127
    ]

    report = {
        "schema_version": 1,
        "assessed_at": datetime.now(UTC).isoformat(),
        "scanned_at": scanned_at.isoformat(),
        "scan_age_days": round(age.total_seconds() / 86400, 2),
        "scan_is_stale": stale,
        "sla_days": SLA_DAYS,
        "kev_catalogue": {"state": kev_state, "entries": len(kev), "path": str(arguments.kev)},
        "findings": len(obligations),
        "overdue": overdue,
        "unexecuted_scanners": unexecuted,
        "status": "PASS" if not (stale or overdue or unexecuted) else "FAIL",
        "interpretation": (
            "A scan older than the interval is not a pass: the most common way a "
            "dependency policy fails is that the scan quietly stopped and the last green "
            "report kept being the answer. A scanner that reported 127 did not run, which "
            "is neither clean nor a finding. With no KEV catalogue loaded, every finding "
            "is `kev_unknown` rather than not-exploited — assuming absence from a list "
            "nobody opened is the failure this project is about."
        ),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
