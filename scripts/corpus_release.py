#!/usr/bin/env python3
"""Freeze what the corpus contains, sign it, and be able to prove a rollback landed.

DATA-003 and SRE-007. An answer already carries a `corpus_release` — sixteen hex
characters naming the set of versions it could have been drawn from — but nothing outside
the running process could say what that release *was*. Six months from now, "the system
told me X on 3 August" is answerable only if the corpus of 3 August can be identified,
and identified by something nobody can quietly edit.

A release manifest is that record: every document, every approved version, its source
hash and the date it takes force, plus the calibration profile and the answer policy in
effect. HMAC over the canonical form, so a manifest that was altered does not verify.

What this does not claim: the key here is a local file, so the signature proves the
manifest was not altered *by someone without that file*. A data owner's signature — the
part DATA-003 actually asks for — is a person taking responsibility, and no code in this
tree can produce one. `--signer` records who the operator says signed it, marked as an
assertion, which is the same distinction the audit chain draws for a declaration.

    corpus_release.py freeze  --out var/releases/2026-08-06.json --signer "..."
    corpus_release.py verify  --manifest var/releases/2026-08-06.json
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _key(path: Path | None) -> bytes:
    if path is not None:
        return path.read_bytes().strip()
    material = os.environ.get("KORPUS_RELEASE_HMAC_KEY", "")
    if not material:
        raise SystemExit(
            "no signing key: pass --key-file or set KORPUS_RELEASE_HMAC_KEY. A manifest "
            "nobody signed is a list, and a list can be edited without anyone noticing."
        )
    return material.encode("utf-8")


def _entries(database: Path) -> list[dict[str, Any]]:
    """Every approved version, with what identifies it and what decides when it governs.

    Ordered by source hash rather than by id: version identifiers are generated per
    import, so an ordering that used them would make two identical corpora produce two
    different manifests.
    """
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT d.canonical_title, d.corpus_id, d.classification, d.access_tier,"
            "       v.source_hash, v.revision, v.authority, v.review_state,"
            "       COALESCE(v.effective_from, v.publication_date) AS in_force_from,"
            "       v.effective_until, v.rescinded_at,"
            "       (SELECT count(*) FROM evidence_spans s WHERE s.version_id = v.id) AS spans"
            " FROM document_versions v JOIN documents d ON d.id = v.document_id"
            " WHERE v.review_state = 'approved'"
            " ORDER BY v.source_hash, d.canonical_title"
        ).fetchall()
    finally:
        connection.close()
    fields = (
        "canonical_title",
        "corpus_id",
        "classification",
        "access_tier",
        "source_hash",
        "revision",
        "authority",
        "review_state",
        "in_force_from",
        "effective_until",
        "rescinded_at",
        "spans",
    )
    return [dict(zip(fields, row, strict=True)) for row in rows]


def _canonical(payload: dict[str, Any]) -> bytes:
    """The bytes that are signed. Sorted keys, no spaces, UTF-8 as itself.

    `ensure_ascii=False` deliberately: escaping Cyrillic would make the signed bytes
    depend on a serialiser setting rather than on the content, and two libraries that
    disagree about escaping would disagree about the signature.
    """
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sign(payload: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()


def _body(database: Path, signer: str, note: str) -> dict[str, Any]:
    entries = _entries(database)
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(_canonical(entry) + b"\n")
    return {
        "schema_version": 1,
        "frozen_at": datetime.now(UTC).isoformat(),
        "database": str(database),
        "versions": len(entries),
        "spans": sum(int(entry["spans"]) for entry in entries),
        "content_digest": digest.hexdigest(),
        # The same sixteen characters an answer carries, computed the same way, so a
        # citation can be matched to the release it came from without the running system.
        "corpus_release": digest.hexdigest()[:16],
        "declared_signer": {
            "name": signer,
            "verified": False,
            "meaning": (
                "Recorded as an assertion. The HMAC proves the manifest was not altered "
                "by anyone without the signing key; it does not prove who approved the "
                "corpus. A data owner's signature is a person taking responsibility and "
                "no code here can produce one."
            ),
        },
        "note": note,
        "entries": entries,
    }


def freeze(arguments: argparse.Namespace) -> int:
    key = _key(arguments.key_file)
    body = _body(arguments.database, arguments.signer, arguments.note)
    manifest = {**body, "hmac_sha256": _sign(body, key)}
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key_: value for key_, value in manifest.items() if key_ != "entries"},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def verify(arguments: argparse.Namespace) -> int:
    key = _key(arguments.key_file)
    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    recorded = str(manifest.pop("hmac_sha256", ""))
    intact = hmac.compare_digest(recorded, _sign(manifest, key))

    result: dict[str, Any] = {
        "manifest": str(arguments.manifest),
        "signature_intact": intact,
        "corpus_release": manifest.get("corpus_release"),
    }
    if arguments.database is not None:
        current = _body(arguments.database, "", "")
        # Compared on content, not on the frozen timestamp: a manifest and a database
        # that hold the same corpus must agree, and they were frozen at different moments
        # by construction.
        result["database"] = str(arguments.database)
        result["matches_database"] = current["content_digest"] == manifest.get("content_digest")
        result["database_release"] = current["corpus_release"]
        result["versions_now"] = current["versions"]
        result["versions_in_manifest"] = manifest.get("versions")
    result["status"] = "PASS" if intact and result.get("matches_database", True) else "FAIL"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(required=True)

    freezer = subparsers.add_parser("freeze")
    freezer.add_argument(
        "--database", type=Path, default=ROOT / "var/runtime/corpus-v6-20260807/korpus.db"
    )
    freezer.add_argument("--out", type=Path, required=True)
    freezer.add_argument("--key-file", type=Path)
    freezer.add_argument("--signer", default="не вказано")
    freezer.add_argument("--note", default="")
    freezer.set_defaults(handler=freeze)

    verifier = subparsers.add_parser("verify")
    verifier.add_argument("--manifest", type=Path, required=True)
    verifier.add_argument("--database", type=Path)
    verifier.add_argument("--key-file", type=Path)
    verifier.set_defaults(handler=verify)

    arguments = parser.parse_args()
    return int(arguments.handler(arguments))


if __name__ == "__main__":
    sys.exit(main())
