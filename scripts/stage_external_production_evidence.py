#!/usr/bin/env python3
"""Stage externally controlled production evidence; downstream gates still verify it."""
from __future__ import annotations
import json, os, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    "reliability": (
        ("KORPUS_EXTERNAL_LOAD_REPORT_FILE", ROOT / "var/load-probe.json"),
        ("KORPUS_EXTERNAL_LOAD_ATTESTATION_FILE", ROOT / "var/production/load-probe.attestation.json"),
        ("KORPUS_EXTERNAL_RECOVERY_REPORT_FILE", ROOT / "var/recovery-report.json"),
        ("KORPUS_EXTERNAL_RECOVERY_ATTESTATION_FILE", ROOT / "var/production/recovery-report.attestation.json"),
    ),
    "tevv": (
        ("KORPUS_EXTERNAL_TEVV_EVIDENCE_FILE", ROOT / "var/production/tevv-evidence.json"),
        ("KORPUS_EXTERNAL_TEVV_ATTESTATION_FILE", ROOT / "var/production/tevv-evidence.attestation.json"),
    ),
    "redteam": (
        ("KORPUS_EXTERNAL_REDTEAM_REPORT_FILE", ROOT / "var/production/external-redteam-report.json"),
        ("KORPUS_EXTERNAL_REDTEAM_ATTESTATION_FILE", ROOT / "var/production/external-redteam-attestation.json"),
    ),
}


def _stage_group(name: str, specs: tuple[tuple[str, Path], ...]) -> dict[str, object]:
    supplied = [(env, Path(os.environ[env])) for env, _ in specs if os.environ.get(env)]
    if not supplied:
        return {"group": name, "status": "NO_EXTERNAL_EVIDENCE", "staged": []}
    if len(supplied) != len(specs):
        missing = [env for env, _ in specs if not os.environ.get(env)]
        raise ValueError(f"external {name} evidence is partial; missing: {missing}")
    staged: list[str] = []
    for (env, destination), (_, source) in zip(specs, supplied, strict=True):
        if not source.is_file():
            raise ValueError(f"{env} does not name a readable file: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        staged.append(str(destination.relative_to(ROOT)))
    return {"group": name, "status": "STAGED_FOR_VERIFICATION", "staged": staged}


def stage() -> dict[str, object]:
    results = [_stage_group(name, specs) for name, specs in GROUPS.items()]
    return {"status": "STAGED" if any(item["staged"] for item in results) else "NO_EXTERNAL_EVIDENCE", "groups": results}


def main() -> int:
    print(json.dumps(stage(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
