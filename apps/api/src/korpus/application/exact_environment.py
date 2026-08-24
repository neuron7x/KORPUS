from __future__ import annotations

from collections.abc import Collection, Mapping


def exact_environment_state(
    locked: Mapping[str, str],
    installed: Mapping[str, str],
    *,
    python_version: str,
    required_python: str,
    allowed_unmanaged: Collection[str],
    hashes_complete: bool,
) -> tuple[dict[str, bool], list[str], dict[str, dict[str, str | None]], list[str]]:
    missing = sorted(name for name in locked if name not in installed)
    mismatched = {
        name: {"locked": version, "installed": installed.get(name)}
        for name, version in locked.items()
        if installed.get(name) not in {None, version}
    }
    allowed = {name.lower().replace("_", "-") for name in allowed_unmanaged}
    extras = sorted(set(installed) - set(locked) - allowed)
    checks = {
        "all_locked_components_installed": not missing,
        "all_versions_exact": not mismatched,
        "no_unmanaged_distributions": not extras,
        "production_python_exact": python_version == required_python,
        "lock_hashes_present": hashes_complete,
    }
    return checks, missing, mismatched, extras
