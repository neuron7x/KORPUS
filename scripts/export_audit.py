#!/usr/bin/env python3
"""Export a continuous batch of audit events for a downstream collector.

Writes JSON Lines to `var/audit-export/` alongside a manifest, and advances a cursor
so the next run continues where this one stopped. Refuses to write a batch whose
sequences jump or whose hash links do not join: a collector cannot detect a missing
event by itself, and a gap shipped quietly becomes a clean audit trail over a hole.

Payloads stay behind unless `--include-payloads` is given. Audit payloads quote corpus
material, and a SIEM is routinely a lower-classification system than the corpus; the
digest travels instead, so a payload can be matched later without having left.

    scripts/export_audit.py [--limit N] [--include-payloads] [--cursor N]

Exit codes: 0 wrote a batch (possibly empty), 1 the batch was not continuous.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.audit_export import (  # noqa: E402
    ExportContinuityError,
    batch_manifest,
    build_records,
    to_jsonl,
    verify_continuity,
)
from korpus.application.policy import PolicyEngine  # noqa: E402
from korpus.config import Settings  # noqa: E402
from korpus.infrastructure.repository import SqlRepository, audits  # noqa: E402
from sqlalchemy import inspect, select  # noqa: E402

OUTPUT_DIR = ROOT / "var/audit-export"
CURSOR = OUTPUT_DIR / "cursor.json"


def _cursor() -> int:
    if not CURSOR.is_file():
        return 1
    return int(json.loads(CURSOR.read_text(encoding="utf-8"))["next_sequence"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--include-payloads", action="store_true")
    parser.add_argument("--cursor", type=int, default=None)
    arguments = parser.parse_args()

    settings = Settings()
    repository = SqlRepository(
        settings.database_url,
        settings.resolved_audit_hmac_key,
        PolicyEngine(),
        settings.audit_anchor_path,
    )
    start = arguments.cursor if arguments.cursor is not None else _cursor()
    statement = (
        select(
            audits.c.sequence,
            audits.c.event_id,
            audits.c.occurred_at,
            audits.c.actor_subject,
            audits.c.action,
            audits.c.resource_type,
            audits.c.resource_id,
            audits.c.payload_json,
            audits.c.previous_hash,
            audits.c.event_hash,
        )
        .where(audits.c.sequence >= start)
        .order_by(audits.c.sequence)
        .limit(max(1, arguments.limit))
    )
    if "audit_events" not in set(inspect(repository.engine).get_table_names()):
        # A traceback here reads as a broken exporter. The database simply has no
        # schema yet, and the operator needs to know which of those two it is.
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "reason": "the configured database has no audit_events table; "
                    "run the migrations before exporting",
                    "database": settings.database_url.split("@")[-1],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    with repository.engine.begin() as connection:
        rows = [dict(row) for row in connection.execute(statement).mappings().all()]

    records = build_records(rows, include_payload=arguments.include_payloads)
    try:
        verify_continuity(records, expected_first_sequence=start)
    except ExportContinuityError as error:
        print(json.dumps({"status": "FAIL", "reason": str(error)}, ensure_ascii=False, indent=2))
        return 1

    manifest = batch_manifest(records, include_payload=arguments.include_payloads)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if records:
        batch_path = OUTPUT_DIR / f"audit-{records[0].sequence}-{records[-1].sequence}.jsonl"
        batch_path.write_text(to_jsonl(records), encoding="utf-8")
        manifest["path"] = str(batch_path.relative_to(ROOT))
        # Advance only after the batch is on disk: a cursor moved first would skip the
        # batch permanently if the write failed.
        CURSOR.write_text(
            json.dumps({"next_sequence": manifest["next_cursor"]}, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
