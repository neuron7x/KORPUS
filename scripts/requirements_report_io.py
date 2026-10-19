"""Publish or verify the generated requirements register without rewriting in CI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def emit_register(path: Path, text: str, payload: dict[str, Any]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            payload = {
                **payload,
                "status": "FAIL",
                "reason": "requirements register is stale",
            }
    else:
        path.write_text(text, encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1
