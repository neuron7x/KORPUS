"""Select one explicit security-evidence class for the audit-closure report."""

from __future__ import annotations

from dataclasses import dataclass

CI_SECURITY_SUMMARY = "var/security/summary.json"
LOCAL_SECURITY_SUMMARY = "var/security/local-summary.json"
SECURITY_FINDING = "SUP-005"


@dataclass(frozen=True)
class EvidenceSelection:
    references: dict[str, list[str]]
    security_summary: str
    security_summary_class: str

    @property
    def metadata(self) -> dict[str, str]:
        return {
            "security_summary": self.security_summary,
            "security_summary_class": self.security_summary_class,
        }


def evidence_for_run(
    source: dict[str, list[str]], *, local_security_summary: bool
) -> EvidenceSelection:
    """Copy the registry and substitute exactly one named scanner-evidence class."""
    selected = {finding: list(references) for finding, references in source.items()}
    scanner_references = selected.get(SECURITY_FINDING, [])
    if scanner_references.count(CI_SECURITY_SUMMARY) != 1:
        raise RuntimeError(f"{SECURITY_FINDING} must cite {CI_SECURITY_SUMMARY} exactly once")
    if LOCAL_SECURITY_SUMMARY in scanner_references:
        raise RuntimeError(
            f"{SECURITY_FINDING} source registry must not cite local scanner evidence"
        )
    summary = LOCAL_SECURITY_SUMMARY if local_security_summary else CI_SECURITY_SUMMARY
    selected[SECURITY_FINDING] = [
        summary if item == CI_SECURITY_SUMMARY else item for item in scanner_references
    ]
    return EvidenceSelection(
        references=selected,
        security_summary=summary,
        security_summary_class=(
            "LOCAL_SCANNERS" if local_security_summary else "PINNED_CI_SCANNERS"
        ),
    )
