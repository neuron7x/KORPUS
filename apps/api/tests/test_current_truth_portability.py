from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts.release_identity import release_tag

ROOT = Path(__file__).resolve().parents[3]


def test_release_identity_can_be_read_from_foreign_root(tmp_path: Path) -> None:
    target = tmp_path / "snapshot"
    (target / "apps/api/src/korpus").mkdir(parents=True)
    shutil.copy2(ROOT / "apps/api/src/korpus/release.json", target / "apps/api/src/korpus/release.json")
    assert release_tag(target) == release_tag(ROOT)


def test_current_release_envelope_is_not_stale() -> None:
    envelope = json.loads((ROOT / "RELEASE_ENVELOPE.json").read_text(encoding="utf-8"))
    assert envelope["release"] == release_tag(ROOT)
