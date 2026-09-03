#!/usr/bin/env python3
"""Assemble the fail-closed production assurance verdict from current gate artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))

from korpus.application.production_assurance import evaluate_production_assurance  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402

DEFAULT_GATES = {
    "engineering": "engineering-gate.json",
    "tevv": "tevv-gate.json",
    "observability": "observability-gate.json",
    "state_contracts": "state-contracts-gate.json",
    "authorization": "authorization-gate.json",
    # Доказ червоної команди цього релізу — ВНУТРІШНЯ змагальна кампанія: зовнішнього
    # незалежного оцінювача немає (модель урядування, 03.09.2026), і `redteam-gate.json`
    # лишається порожнім назавжди. Читати його означало б тримати гейт, якого ніхто не
    # може пройти. Клас доказу видно в самому артефакті: INTERNAL_ADVERSARIAL.
    "redteam": "redteam_internal-gate.json",
    "reliability": "reliability-gate.json",
    "inference_security": "inference_security-gate.json",
    "postgres_security": "postgres_security-gate.json",
    "supply_chain": "supply_chain-gate.json",
    "exact_environment": "exact_environment-gate.json",
    "mutation": "mutation-gate.json",
    "pec_authority": "pec_authority-gate.json",
    "pec_canary": "pec_canary-gate.json",
}


def _load(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile", type=Path, default=ROOT / "config/assurance/production-v1.json"
    )
    parser.add_argument("--gate-dir", type=Path, default=ROOT / "var/production")
    parser.add_argument(
        "--out", type=Path, default=ROOT / "reports/PRODUCTION_ASSURANCE_REPORT.json"
    )
    args = parser.parse_args()
    profile_path, gate_dir, out_path = (
        args.profile.resolve(),
        args.gate_dir.resolve(),
        args.out.resolve(),
    )
    profile = _load(profile_path)
    source = compute_source_digest(ROOT)
    release = release_tag()
    gates = {gate: _load(gate_dir / filename) for gate, filename in DEFAULT_GATES.items()}
    verdict = evaluate_production_assurance(profile, gates, source_digest=source, release=release)
    gate_hashes = {
        gate: hashlib.sha256((gate_dir / filename).read_bytes()).hexdigest()
        for gate, filename in DEFAULT_GATES.items()
        if (gate_dir / filename).is_file()
    }
    payload = {
        "schema": "korpus.production-assurance.v1",
        "status": verdict.status,
        "release": release,
        "source_tree_sha256": source,
        "profile": str(profile_path.relative_to(ROOT)),
        "profile_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        "checks": dict(verdict.checks),
        "failures": list(verdict.failures),
        "gate_sha256": gate_hashes,
        "gates": gates,
        "production_authorized": verdict.passed,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: payload[k]
                for k in (
                    "status",
                    "release",
                    "source_tree_sha256",
                    "failures",
                    "production_authorized",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if verdict.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
