#!/usr/bin/env python3
"""Create and verify authenticated PostgreSQL backup manifests."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
from pathlib import Path
from typing import Any

from backup_crypto import load_key

SCHEMA = "korpus-postgres-backup-v4"
DOMAIN = b"KORPUS-BACKUP-MANIFEST-V1\0"
HEX64 = re.compile(r"[0-9a-f]{64}")
KEY_ID = re.compile(r"[A-Za-z0-9._:-]+")


def canonical_bytes(payload: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "manifest_hmac_sha256"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sign(payload: dict[str, Any], key: bytes) -> str:
    return hmac.new(key, DOMAIN + canonical_bytes(payload), hashlib.sha256).hexdigest()


def validate_fields(payload: dict[str, Any], *, expected_file: str, expected_key_id: str) -> None:
    if payload.get("schema") != SCHEMA:
        raise ValueError("backup manifest schema mismatch")
    if payload.get("encrypted") is not True or payload.get("cipher") != "AES-256-GCM":
        raise ValueError("backup manifest cipher mismatch")
    if payload.get("file") != expected_file:
        raise ValueError("backup manifest filename mismatch")
    if payload.get("key_id") != expected_key_id or not KEY_ID.fullmatch(str(payload.get("key_id", ""))):
        raise ValueError("backup key id mismatch")
    for name in ("sha256", "plaintext_sha256", "manifest_hmac_sha256"):
        if not HEX64.fullmatch(str(payload.get(name, ""))):
            raise ValueError(f"invalid backup manifest field: {name}")
    for name in ("bytes", "plaintext_bytes"):
        if not isinstance(payload.get(name), int) or int(payload[name]) <= 0:
            raise ValueError(f"invalid backup manifest field: {name}")


def create(args: argparse.Namespace) -> int:
    key = load_key(args.key_file)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "created_at": args.created_at,
        "encrypted": True,
        "cipher": "AES-256-GCM",
        "sha256": args.sha256,
        "bytes": args.bytes,
        "plaintext_sha256": args.plaintext_sha256,
        "plaintext_bytes": args.plaintext_bytes,
        "file": args.file,
        "key_id": args.key_id,
    }
    payload["manifest_hmac_sha256"] = sign(payload, key)
    validate_fields(payload, expected_file=args.file, expected_key_id=args.key_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(args.output, 0o600)
    return 0


def verify(args: argparse.Namespace) -> int:
    key = load_key(args.key_file)
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("backup manifest is not an object")
    try:
        validate_fields(payload, expected_file=args.expected_file, expected_key_id=args.expected_key_id)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    expected_hmac = sign(payload, key)
    if not hmac.compare_digest(str(payload["manifest_hmac_sha256"]), expected_hmac):
        raise SystemExit("backup manifest authentication failed")
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    creator = subparsers.add_parser("create")
    creator.add_argument("--output", type=Path, required=True)
    creator.add_argument("--key-file", type=Path, required=True)
    creator.add_argument("--created-at", required=True)
    creator.add_argument("--sha256", required=True)
    creator.add_argument("--bytes", type=int, required=True)
    creator.add_argument("--plaintext-sha256", required=True)
    creator.add_argument("--plaintext-bytes", type=int, required=True)
    creator.add_argument("--file", required=True)
    creator.add_argument("--key-id", required=True)
    creator.set_defaults(handler=create)
    verifier = subparsers.add_parser("verify")
    verifier.add_argument("--manifest", type=Path, required=True)
    verifier.add_argument("--key-file", type=Path, required=True)
    verifier.add_argument("--expected-file", required=True)
    verifier.add_argument("--expected-key-id", required=True)
    verifier.set_defaults(handler=verify)
    args = parser.parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
