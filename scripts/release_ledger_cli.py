#!/usr/bin/env python3
"""Inspect and verify a KORPUS release ledger stored as canonical JSON Lines.

The CLI does not authorize promotion and does not mint events from free-form arguments.
Events are created by the domain APIs that execute the actual promotion/withdrawal policy;
this tool is intentionally a verifier/export surface for CI, incident response and an
external head-anchor service.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from korpus.application.release_ledger import ReleaseLedgerEvent, verify_ledger


def load_ledger(path: Path) -> list[ReleaseLedgerEvent]:
    events: list[ReleaseLedgerEvent] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(f"line {line_number}: invalid JSON") from error
        if not isinstance(value, dict):
            raise ValueError(f"line {line_number}: event must be a JSON object")
        try:
            events.append(ReleaseLedgerEvent(**value))
        except (TypeError, ValueError, KeyError) as error:
            raise ValueError(
                f"line {line_number}: invalid release ledger event: {error}"
            ) from error
    return events


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--ledger", type=Path, required=True)
    verify_parser.add_argument("--expected-release-identity-digest")
    verify_parser.add_argument("--expected-head-sha256")

    head_parser = sub.add_parser("head")
    head_parser.add_argument("--ledger", type=Path, required=True)

    args = parser.parse_args()
    try:
        events = load_ledger(args.ledger)
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, indent=2))
        return 1

    if args.command == "head":
        verdict = verify_ledger(events)
        print(
            json.dumps(
                {
                    "status": "PASS" if verdict.valid else "FAIL",
                    "events": verdict.events,
                    "head_sha256": verdict.head_sha256,
                    "failures": list(verdict.failures),
                },
                indent=2,
            )
        )
        return 0 if verdict.valid else 1

    verdict = verify_ledger(
        events,
        expected_release_identity_digest=args.expected_release_identity_digest,
        expected_head_sha256=args.expected_head_sha256,
    )
    print(
        json.dumps(
            {
                "status": "PASS" if verdict.valid else "FAIL",
                "events": verdict.events,
                "head_sha256": verdict.head_sha256,
                "failures": list(verdict.failures),
            },
            indent=2,
        )
    )
    return 0 if verdict.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
