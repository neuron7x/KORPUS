from __future__ import annotations
from pathlib import Path
try:
    from .current_truth_contract import alias_checks as base_alias_checks, load_object
except ImportError:
    from current_truth_contract import alias_checks as base_alias_checks, load_object

def alias_checks(root: Path, release: str) -> dict[str, bool]:
    checks = base_alias_checks(root, release); identity_path = root / "apps/api/src/korpus/release.json"
    if not identity_path.is_file(): return checks | {"release_identity.present": False}
    artifact = str(load_object(identity_path).get("distribution_artifact", ""))
    for name in ("GITHUB_IMPORT.md", "GITLAB_IMPORT.md"):
        path = root / name; checks[f"{name}.present"] = path.is_file()
        if path.is_file():
            text = path.read_text(encoding="utf-8"); checks[f"{name}.release_bound"] = release in text; checks[f"{name}.artifact_bound"] = bool(artifact) and artifact in text
    package_build = root / "PACKAGE_BUILD.json"; checks["PACKAGE_BUILD.present"] = package_build.is_file()
    if package_build.is_file(): checks["PACKAGE_BUILD.release_bound"] = load_object(package_build).get("release") == release
    return checks
