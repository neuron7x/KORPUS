#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.release import RELEASE_TAG, RELEASE_VERSION  # noqa: E402


def _read_json(relative: str) -> dict[str, object]:
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{relative} is not a JSON object")
    return value


def _tag_points_to_head() -> bool:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/tags/{RELEASE_TAG}^{{commit}}"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        return False
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    return completed.stdout.strip() == head


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-git-tag", action="store_true")
    args = parser.parse_args()
    pyproject = tomllib.loads((ROOT / "apps/api/pyproject.toml").read_text(encoding="utf-8"))
    web = _read_json("apps/web/package.json")
    lock = _read_json("apps/web/package-lock.json")
    desired = _read_json("config/operations/desired-state.json")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    checks = {
        "api_pyproject": pyproject.get("project", {}).get("version") == RELEASE_VERSION,
        "web_package": web.get("version") == RELEASE_VERSION,
        "web_lock_root": lock.get("version") == RELEASE_VERSION,
        "web_lock_package": lock.get("packages", {}).get("", {}).get("version") == RELEASE_VERSION,
        "desired_state": desired.get("release") == RELEASE_TAG,
        "readme": readme.startswith(f"# KORPUS v{RELEASE_VERSION}"),
    }
    if args.require_git_tag:
        checks["git_tag_points_to_head"] = _tag_points_to_head()
    failures = sorted(name for name, valid in checks.items() if not valid)
    payload = {
        "valid": not failures,
        "version": RELEASE_VERSION,
        "tag": RELEASE_TAG,
        "checks": checks,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
