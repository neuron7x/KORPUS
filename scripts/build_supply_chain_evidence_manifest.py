#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src")); sys.path.insert(0, str(ROOT / "scripts"))
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402

ARTIFACTS = (
    "source-sbom.cdx.json",
    "api-sbom.cdx.json",
    "web-sbom.cdx.json",
    "var/security/summary.json",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "var/production/supply-chain-evidence-manifest.json")
    args = parser.parse_args()
    artifacts = {}
    for relative in ARTIFACTS:
        path = ROOT / relative
        if not path.is_file():
            raise SystemExit(f"missing supply-chain evidence artifact: {relative}")
        artifacts[relative] = {"sha256": sha(path), "bytes": path.stat().st_size}
    payload = {
        "schema": "korpus.supply-chain-evidence.v1",
        "release": release_tag(),
        "source_tree_sha256": compute_source_digest(ROOT),
        "artifacts": artifacts,
        "evidence_class": "CI_SCANNERS_PLUS_IMAGE_SBOM",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
