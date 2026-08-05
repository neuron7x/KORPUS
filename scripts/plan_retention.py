#!/usr/bin/env python3
"""Emit the retention plan for the configured corpus, and reconcile it with storage.

Writes `var/retention-plan.json`. Deletes nothing, and is not a scheduler: a timer
that removes material from a corpus which answers "which order was in force on date X"
is a data-loss mechanism driven by a config field. The plan is the artefact an owner
reviews before authorising anything.

Exit codes carry the finding, so this can be a gate:

    0  every document has a disposition and the plan matches storage
    1  reconciliation found a difference — the plan describes a system that is not there
    2  material is past its retention period with no deletion permission, or sits in a
       corpus with no governance policy at all. Neither is an error in the code; both
       are decisions nobody has made, and reporting them as "clean" would be the lie.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.retention import (  # noqa: E402  (path set above)
    AWAITING_DECISION,
    UNGOVERNED,
    plan_retention,
    reconcile,
)
from korpus.config import Settings  # noqa: E402
from korpus.domain.models import AccessTier, Identity  # noqa: E402
from korpus.security.corpus_governance import CorpusGovernanceProfile  # noqa: E402

OUTPUT = ROOT / "var/retention-plan.json"


def main() -> int:
    settings = Settings()
    if settings.corpus_governance_profile_path is None:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "reason": "no corpus governance profile is configured, so no retention "
                    "period, owner or legal-hold state exists to plan against",
                },
                indent=2,
            )
        )
        return 2
    profile = CorpusGovernanceProfile.load(
        settings.corpus_governance_profile_path,
        settings.corpus_governance_profile_sha256,
    )

    from korpus.application.policy import PolicyEngine
    from korpus.infrastructure.repository import SqlRepository

    repository = SqlRepository(
        settings.database_url,
        settings.resolved_audit_hmac_key,
        PolicyEngine(),
        settings.audit_anchor_path,
    )
    # The planner must see the whole corpus, including compartments no operator holds:
    # a retention posture computed over one identity's visible subset would report
    # "nothing to decide" about material that identity cannot see.
    surveyor = Identity(
        subject="retention-planner",
        roles=frozenset({"admin", "auditor", "user"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset(profile.corpora),
        compartments=frozenset(),
    )
    documents = [
        (str(document.id), document.corpus_id, document.created_at)
        for document in repository.list_documents(surveyor)
    ]
    plan = plan_retention(documents, profile.corpora)
    problems = reconcile(plan, [document_id for document_id, _, _ in documents])

    rendered = plan.as_dict()
    rendered["reconciliation"] = problems
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(rendered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in rendered.items() if k != "items"}, ensure_ascii=False,
                     indent=2))

    if problems:
        return 1
    undecided = plan.by_disposition(AWAITING_DECISION) + plan.by_disposition(UNGOVERNED)
    return 2 if undecided else 0


if __name__ == "__main__":
    raise SystemExit(main())
