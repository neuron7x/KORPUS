#!/usr/bin/env python3
"""Put a known corpus into the database the recovery drill will back up.

`verify_postgres_restore.py` asserted `count(*) FROM documents >= 2` and passed for as
long as the pytest run that preceded it happened to leave rows behind. On 2026-08-05
it stopped: the restore was correct, the backup was correct, and the drill failed with
"restored corpus rows are missing" because the suite it was standing on had cleaned up
after itself. A drill whose fixture is another job's side effect measures that side
effect.

The rows written here are deterministic and identifiable — every id carries the
RECOVERY_PREFIX — so the verification after the restore can assert *these* rows came
back rather than counting whatever is there. Anything else in the database is somebody
else's data and is not evidence about recovery.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine, text

RECOVERY_PREFIX = "recovery-drill"
# Written *after* the backup is taken, so the restore is expected to lose exactly
# these. Without them "lost_events: 0" is true of any drill that copies a database
# nobody wrote to — a measurement that cannot come out any other way.
POST_BACKUP_PREFIX = "recovery-drill-post"
DOCUMENT_COUNT = 3
POST_BACKUP_COUNT = 5
NAMESPACE = uuid.UUID("6f1d5f9c-1f3e-4f2a-9a1b-9d7a1c0e5b21")


def _identifier(kind: str, index: int) -> uuid.UUID:
    """Stable across runs: a drill that cannot be repeated is not a drill."""
    return uuid.uuid5(NAMESPACE, f"{RECOVERY_PREFIX}:{kind}:{index}")


def main() -> int:
    url = os.environ["KORPUS_RECOVERY_SEED_URL"]
    after_backup = os.environ.get("KORPUS_RECOVERY_PHASE") == "after-backup"
    prefix = POST_BACKUP_PREFIX if after_backup else RECOVERY_PREFIX
    count = POST_BACKUP_COUNT if after_backup else DOCUMENT_COUNT
    engine = create_engine(url, pool_pre_ping=True)
    now = datetime.now(UTC)
    with engine.begin() as connection:
        for index in range(count):
            document_id = _identifier(f"{prefix}-document", index)
            connection.execute(
                text(
                    # `compartments_json` arrived with migration 0004 and this insert
                    # was never updated, so every seeded row failed on a NOT NULL and the
                    # drill measured zero writes after the backup — which the recovery
                    # verdict correctly refuses as "the loss figure could not have come
                    # out any other way". The seeder had been silently writing nothing.
                    "INSERT INTO documents (id, canonical_title, corpus_id, issuer, "
                    "jurisdiction, document_type, access_tier, classification, "
                    "compartments_json, created_at) VALUES (:id, :title, :corpus, "
                    ":issuer, :jurisdiction, :document_type, :access_tier, "
                    ":classification, :compartments, :created_at) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": str(document_id),
                    "title": f"{prefix} document {index}",
                    "corpus": "public",
                    "issuer": "recovery drill",
                    "jurisdiction": "UA",
                    "document_type": "drill",
                    "access_tier": 0,
                    "classification": "public",
                    "compartments": "[]",
                    "created_at": now,
                },
            )
    with engine.begin() as connection:
        rows = int(
            connection.execute(
                text("SELECT count(*) FROM documents WHERE canonical_title LIKE :pattern"),
                {"pattern": f"{prefix} %"},
            ).scalar_one()
        )
    engine.dispose()
    summary = {
        "prefix": prefix,
        "phase": "after-backup" if after_backup else "before-backup",
        "documents_seeded": rows,
        "expected": count,
        "digest": hashlib.sha256(f"{prefix}:{count}".encode()).hexdigest(),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if rows < count:
        raise SystemExit(
            f"seeded {rows} of {count} {prefix} documents; the drill would "
            "measure a database it did not populate"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
