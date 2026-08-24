#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess, sys, tomllib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
from korpus.release import DISTRIBUTION_ARTIFACT, RELEASE_TAG, RELEASE_VERSION  # noqa: E402

def _read_json(relative: str) -> dict[str, object]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{relative} is not a JSON object")
    return value

def _tag_points_to_head() -> bool:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/tags/{RELEASE_TAG}^{{commit}}"],
        cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return False
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()
    return completed.stdout.strip() == head

def _handoff_matches() -> bool:
    state = _read_json("handoff/machine/current_state.json")
    return state.get("canonical_release") == RELEASE_TAG == state.get("handoff_release")

def _gitlab_import_matches() -> bool:
    text = (ROOT / "GITLAB_IMPORT.md").read_text(encoding="utf-8")
    return (
        RELEASE_TAG in text
        and DISTRIBUTION_ARTIFACT in text
        and ".bundle" not in text
    )

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-git-tag", action="store_true")
    args = parser.parse_args()
    pyproject = tomllib.loads((ROOT / "apps/api/pyproject.toml").read_text(encoding="utf-8"))
    web, lock = _read_json("apps/web/package.json"), _read_json("apps/web/package-lock.json")
    desired = _read_json("config/operations/desired-state.json")
    prefix = f"# KORPUS v{RELEASE_VERSION}"
    checks = {
        "api_pyproject": pyproject.get("project", {}).get("version") == RELEASE_VERSION,
        "web_package": web.get("version") == RELEASE_VERSION,
        "web_lock_root": lock.get("version") == RELEASE_VERSION,
        "web_lock_package": lock.get("packages", {}).get("", {}).get("version") == RELEASE_VERSION,
        "desired_state": desired.get("release") == RELEASE_TAG,
        "readme": (ROOT / "README.md").read_text(encoding="utf-8").startswith(prefix),
        "package_index": (ROOT / "FINAL_PACKAGE_CONTENTS.md").read_text(encoding="utf-8").startswith(prefix),
        "distribution_contract": (ROOT / "DISTRIBUTION_CONTENTS.md").read_text(encoding="utf-8").startswith(prefix),
        "package_description": (ROOT / "WHAT_IS_IN_THIS_PACKAGE.md").read_text(encoding="utf-8").startswith(prefix),
        "gitlab_import": _gitlab_import_matches(),
        "handoff_release": _handoff_matches(),
    }
    if args.require_git_tag:
        checks["git_tag_points_to_head"] = _tag_points_to_head()
    failures = sorted(name for name, valid in checks.items() if not valid)
    payload = {"valid": not failures, "version": RELEASE_VERSION, "tag": RELEASE_TAG, "checks": checks}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1

if __name__ == "__main__":
    raise SystemExit(main())
