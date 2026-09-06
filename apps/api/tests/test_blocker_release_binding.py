"""`BLOCKER_REGISTRY.release_bound_current` — єдина з шести перевірок реєстру, яку
не вбиває ніщо. Її сусідка `source_bound_current` має тест; ця не мала.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.current_truth_admission import blocker_state_checks

DIGEST = "a" * 64
RELEASE = "v0.9.7"


def _registry(root: Path, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "release": RELEASE,
        "source_tree_sha256": DIGEST,
        "hard_predicate_report_current": True,
        "internal_executable_unresolved": 0,
        "evidence_sha256": {},
    }
    payload.update(overrides)
    path = root / f"reports/release/{RELEASE}/final/BLOCKER_REGISTRY.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return root


def test_a_registry_for_this_release_is_release_bound(tmp_path: Path) -> None:
    checks = blocker_state_checks(_registry(tmp_path), RELEASE, DIGEST)
    assert checks["BLOCKER_REGISTRY.release_bound_current"] is True
    assert checks["BLOCKER_REGISTRY.source_bound_current"] is True


def test_a_registry_about_another_release_is_not_release_bound(tmp_path: Path) -> None:
    """Дайджест дерева тут ТОЙ САМИЙ: без окремої перевірки релізу реєстр v0.9.6,
    зібраний на цьому ж дереві, читався б як поточний."""
    checks = blocker_state_checks(_registry(tmp_path, release="v0.9.6"), RELEASE, DIGEST)
    assert checks["BLOCKER_REGISTRY.release_bound_current"] is False
    assert checks["BLOCKER_REGISTRY.source_bound_current"] is True
