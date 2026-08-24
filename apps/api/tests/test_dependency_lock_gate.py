from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_dependency_locks import verify


def seed(root: Path) -> None:
    api = root / "apps/api"
    web = root / "apps/web"
    api.mkdir(parents=True)
    web.mkdir(parents=True)
    (api / "pyproject.toml").write_text(
        """[project]\nname="x"\nversion="1.0"\ndependencies=["fastapi>=0.1,<2"]\n[project.optional-dependencies]\ndev=["pytest>=9,<10"]\npostgres=[]\n""",
        encoding="utf-8",
    )
    (api / "requirements.runtime.lock").write_text(
        "fastapi==1.0.0 \\\n    --hash=sha256:" + "a" * 64 + "\n",
        encoding="utf-8",
    )
    (api / "requirements.dev.lock").write_text(
        "-r requirements.runtime.lock\npytest==9.0.3 \\\n    --hash=sha256:" + "b" * 64 + "\n",
        encoding="utf-8",
    )
    (web / "package.json").write_text(
        json.dumps({"name": "web", "version": "1.0.0", "dependencies": {}, "devDependencies": {}}),
        encoding="utf-8",
    )
    (web / "package-lock.json").write_text(
        json.dumps(
            {
                "name": "web",
                "version": "1.0.0",
                "lockfileVersion": 3,
                "packages": {
                    "": {
                        "name": "web",
                        "version": "1.0.0",
                        "dependencies": {},
                        "devDependencies": {},
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_exact_hashed_lock_closure_passes(tmp_path: Path) -> None:
    seed(tmp_path)
    report = verify(tmp_path)
    assert report["status"] == "PASS", report["failures"]
    assert report["python"]["all_pins_exact"] is True
    assert report["vulnerability_status"].startswith("UNKNOWN_UNTIL")


def test_unpinned_dependency_fails_closed(tmp_path: Path) -> None:
    seed(tmp_path)
    (tmp_path / "apps/api/requirements.runtime.lock").write_text("fastapi>=1.0\n", encoding="utf-8")
    report = verify(tmp_path)
    assert report["status"] == "FAIL"
    assert any("not an exact == pin" in item for item in report["failures"])


def test_direct_url_dependency_fails_closed(tmp_path: Path) -> None:
    seed(tmp_path)
    (tmp_path / "apps/api/requirements.runtime.lock").write_text(
        "fastapi @ https://example.invalid/pkg.whl\n", encoding="utf-8"
    )
    report = verify(tmp_path)
    assert report["status"] == "FAIL"
    assert any("non-hermetic requirement" in item for item in report["failures"])
