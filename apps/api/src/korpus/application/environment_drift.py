"""Comparing what is running against what was approved, and refusing to guess.

OPS-004: "No evidence of desired-state vs live infrastructure reconciliation", with an
acceptance predicate of "Unauthorized drift detected and reverted/blocked."

`config/operations/desired-state-v5.json` already fingerprints what the repository
declares. What did not exist was anything to compare a *running* environment against
it, and — the harder half — anything that distinguished the three answers a comparison
can have. Only two of them are usually implemented:

    IN_SYNC       every declared artefact is present with the approved digest
    DRIFTED       something present differs from what was approved
    UNOBSERVED    the live environment did not report on this artefact at all

The third is the one that matters and the one that gets folded into "in sync" by
accident. A reconciler that receives a partial observation and reports no drift is
reporting on the subset it happened to see, and an artefact removed from the cluster
entirely — the change most worth catching — produces exactly that partial observation.
So an unobserved artefact is a finding, not a silence.

`EXTRA` is separate from `DRIFTED` for the same reason a missing thing differs from a
changed thing: something running that nothing declared was never reviewed at all, and
naming it "drift" would put it in the same bucket as a version bump.

What this module does not do is read a cluster or revert anything. It takes an observed
state as input and returns a verdict; obtaining that observation from a live cluster,
and acting on the verdict, is the operator's half and stays external evidence — which
is the same boundary the recovery drill and TEVV sit on.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

IN_SYNC = "IN_SYNC"
DRIFTED = "DRIFTED"
UNOBSERVED = "UNOBSERVED"
EXTRA = "EXTRA"


@dataclass(frozen=True)
class DriftFinding:
    path: str
    state: str
    approved_sha256: str | None
    observed_sha256: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "state": self.state,
            "approved_sha256": self.approved_sha256,
            "observed_sha256": self.observed_sha256,
        }


@dataclass(frozen=True)
class DriftReport:
    checked: int
    findings: tuple[DriftFinding, ...]

    def of_state(self, state: str) -> tuple[DriftFinding, ...]:
        return tuple(finding for finding in self.findings if finding.state == state)

    @property
    def in_sync(self) -> bool:
        return not self.findings

    @property
    def status(self) -> str:
        return IN_SYNC if self.in_sync else DRIFTED

    def as_dict(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.state] = counts.get(finding.state, 0) + 1
        return {
            "schema_version": 1,
            "status": self.status,
            "artefacts_declared": self.checked,
            "counts": counts,
            "findings": [finding.as_dict() for finding in self.findings],
            "interpretation": (
                "Compares an observed environment against the approved desired state. "
                "UNOBSERVED is a finding, not a silence: a reconciler that receives a "
                "partial observation and reports no drift is reporting on whatever "
                "subset it happened to see, and an artefact deleted from the cluster "
                "produces exactly that. Obtaining the observation from a live cluster "
                "and acting on this verdict is the operator's half."
            ),
        }


def compare(
    desired: Mapping[str, str], observed: Mapping[str, str | None]
) -> DriftReport:
    """Compare approved digests against observed ones.

    `desired` maps path to the approved sha256; `observed` maps path to what the
    environment reports, with `None` for "present but unreadable". A path absent from
    `observed` is unobserved, which is not the same as absent from the environment —
    the reconciler cannot tell those apart, and saying so is the honest output.
    """
    findings: list[DriftFinding] = []
    for path in sorted(desired):
        approved = desired[path]
        if path not in observed:
            findings.append(DriftFinding(path, UNOBSERVED, approved, None))
            continue
        seen = observed[path]
        if seen is None:
            findings.append(DriftFinding(path, UNOBSERVED, approved, None))
        elif seen != approved:
            findings.append(DriftFinding(path, DRIFTED, approved, seen))
    for path in sorted(set(observed) - set(desired)):
        findings.append(DriftFinding(path, EXTRA, None, observed[path]))
    return DriftReport(checked=len(desired), findings=tuple(findings))


def desired_from_manifest(manifest: Mapping[str, Any]) -> dict[str, str]:
    """The approved digests, read from the desired-state manifest.

    Read rather than recomputed: recomputing from the working tree would compare the
    environment against whatever is checked out, which answers a different question and
    would report IN_SYNC on a machine with uncommitted changes.
    """
    records = manifest.get("records")
    if not isinstance(records, list):
        raise ValueError("desired-state manifest has no records list")
    return {str(record["path"]): str(record["sha256"]) for record in records}


#: How old an observation may be before it stops describing the environment. OPS-004
#: asks for "periodic attestation", and the failure that makes periodicity necessary is
#: not a missing check — it is a passing one: an observation taken before the change,
#: compared afterwards, reports IN_SYNC about a machine that has since drifted. A
#: comparator that cannot tell yesterday's evidence from today's is a comparator whose
#: verdict is about the past.
DEFAULT_MAX_AGE_SECONDS = 3600


def observation_age_admissible(
    observed_at: str | None, now: datetime, max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS
) -> tuple[bool, str]:
    """Whether an observation is recent enough to be compared.

    An observation without a timestamp is refused rather than assumed fresh: the whole
    point of the check is that a stale answer and a current one are indistinguishable
    once the verdict is printed.
    """
    if not observed_at:
        return False, (
            "the observation carries no timestamp, so it cannot be told from one taken "
            "before the change it is meant to detect"
        )
    try:
        taken = datetime.fromisoformat(observed_at)
    except ValueError:
        return False, f"the observation timestamp is not an ISO instant: {observed_at!r}"
    if taken.tzinfo is None:
        return False, "the observation timestamp carries no timezone"
    age = (now - taken).total_seconds()
    if age < -60:
        # More than a minute in the future is a clock the operator cannot reason about,
        # and it is also how a replayed observation would be made to look fresh.
        return False, f"the observation is dated {abs(age):.0f}s in the future"
    if age > max_age_seconds:
        return False, (
            f"the observation is {age:.0f}s old, past the {max_age_seconds}s limit; "
            "it describes the environment as it was, not as it is"
        )
    return True, f"the observation is {max(age, 0):.0f}s old"


def blocked(report: DriftReport) -> tuple[bool, str]:
    """Whether this environment may serve.

    The acceptance predicate says unauthorized drift is "detected and reverted/blocked".
    Detection is this module; blocking is the caller's, and it needs a single answer
    rather than a list to reason about.
    """
    if report.in_sync:
        return False, "the environment matches the approved desired state"
    drifted = len(report.of_state(DRIFTED))
    unobserved = len(report.of_state(UNOBSERVED))
    extra = len(report.of_state(EXTRA))
    return True, (
        f"{drifted} artefacts differ from the approved state, {unobserved} were not "
        f"observed, {extra} are running undeclared"
    )
