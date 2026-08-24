#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from full_ssot_packager import build
from release_identity import load_release_identity

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    identity = load_release_identity(root)
    out = args.out or (root.parent / identity["distribution_artifact"])
    out = out if out.is_absolute() else root / out
    payload = build(root, out)
    out.with_suffix(out.suffix + ".sha256").write_text(
        f"{payload['sha256']}  {out.name}\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
