from __future__ import annotations

import sys
from pathlib import Path


def pytest_environment(root: Path, python: Path | None = None) -> dict[str, str]:
    executable = python or Path(sys.executable)
    external_home = root.parent / f".{root.name}-pytest-home"
    return {
        "HOME": str(external_home),
        "XDG_CACHE_HOME": str(external_home / "cache"),
        "PATH": f"{executable.parent}:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONPATH": f"{root / 'apps/api/src'}:{root / 'scripts'}:{root}",
    }
