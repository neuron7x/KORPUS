#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from manifest_lib.source_manifest import verify_source_manifest

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    failures, summary = verify_source_manifest(ROOT)
    if failures:
        print(json.dumps({"valid": False, "failures": failures}, indent=2))
        return 1
    print(json.dumps({"valid": True, **summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
