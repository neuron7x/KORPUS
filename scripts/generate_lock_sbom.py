#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.source_security_lock import build_lock_sbom  # noqa: E402


def main() -> int:
    bom = build_lock_sbom(ROOT)
    out = ROOT / "source-sbom.cdx.json"
    out.write_text(json.dumps(bom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS",
                "components": len(bom["components"]),
                "path": str(out.relative_to(ROOT)),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
