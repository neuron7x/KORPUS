#!/usr/bin/env python3
"""What would be deleted from the conversation history, and — only if asked — deleting it.

The corpus has had a retention policy since v5. Conversations did not: `conversations` and
`messages` grew without bound and appeared in no disposition plan at all. A question a
soldier asked was kept for ever, by nobody's decision.

Two modes, and the default is the harmless one:

    conversation_retention.py                 # prints the plan, deletes nothing
    conversation_retention.py --apply         # deletes what the plan named, with an audit event

Exit codes are the report: `0` when nothing is due, `1` when a window is declared and
something is past it, `2` when no window is declared. The last is not a crash and not a
pass — it is the finding. Nobody has decided how long a soldier's questions are kept, and a
job that printed `PASS` for that state is how the decision never gets made.

The window comes from `KORPUS_CONVERSATION_RETENTION_DAYS` and is refused below seven days
(it would delete a shift's history while the shift is still running) and above ten years
(indistinguishable from for ever).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.conversation_retention import (  # noqa: E402  (path set above)
    InvalidRetentionWindow,
    RetentionState,
    plan_retention,
)


def _window() -> int | None:
    raw = os.getenv("KORPUS_CONVERSATION_RETENTION_DAYS", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as error:
        raise InvalidRetentionWindow(f"not a number of days: {raw!r}") from error


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=os.getenv("KORPUS_DATABASE_URL", ""))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="delete what the plan names; without it nothing is removed",
    )
    parser.add_argument("--out", type=Path, default=ROOT / "var/conversation-retention.json")
    arguments = parser.parse_args()

    if not arguments.database_url:
        raise SystemExit("KORPUS_DATABASE_URL or --database-url is required")

    from korpus.application.policy import PolicyEngine
    from korpus.infrastructure.conversation_repository import SqlConversationStore
    from korpus.infrastructure.repository import SqlRepository
    from korpus.infrastructure.tenancy_repository import system_actor

    repository = SqlRepository(
        arguments.database_url,
        os.getenv("KORPUS_AUDIT_HMAC_KEY", "retention"),
        PolicyEngine(),
        Path(os.getenv("KORPUS_AUDIT_ANCHOR_PATH", ROOT / "var/audit-anchor.json")),
    )
    try:
        store = SqlConversationStore(repository)
        try:
            window = _window()
        except InvalidRetentionWindow as refusal:
            print(json.dumps({"status": "INVALID_WINDOW", "detail": str(refusal)}, indent=2))
            return 2

        try:
            plan = plan_retention(store.all_conversations_by_activity(), window_days=window)
        except InvalidRetentionWindow as refusal:
            print(json.dumps({"status": "INVALID_WINDOW", "detail": str(refusal)}, indent=2))
            return 2

        report = plan.as_report()
        report["applied"] = False

        if arguments.apply and plan.state is RetentionState.NOT_DECLARED:
            # `--apply` with no window is the command that would delete everything or
            # nothing depending on a default nobody chose. Refused rather than guessed at.
            report["detail"] = "refusing to apply a retention policy nobody has declared"
            _write(arguments.out, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2

        if arguments.apply and plan.expired:
            identifiers = [item.conversation_id for item in plan.expired]
            removed = store.delete_conversations(identifiers)
            repository.append_audit(
                system_actor("retention"),
                "conversation.retention_applied",
                "conversation",
                None,
                {
                    "window_days": plan.window_days,
                    "conversations_deleted": len(identifiers),
                    "messages_deleted": removed,
                    "evaluated_at": datetime.now(UTC).isoformat(),
                    "interpretation": (
                        "Conversation history past the declared window was erased. The "
                        "identifiers are not recorded here: an audit event naming every "
                        "deleted conversation would preserve exactly what the deletion "
                        "was for."
                    ),
                },
            )
            report["applied"] = True
            report["messages_deleted"] = removed
            report["conversations_deleted"] = len(identifiers)

        _write(arguments.out, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if plan.state is RetentionState.NOT_DECLARED:
            return 2
        return 1 if plan.expired and not report["applied"] else 0
    finally:
        repository.close()


def _write(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
