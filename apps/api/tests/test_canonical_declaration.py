"""Ім'я канонічної гілки читається з ОДНОГО місця, і мовчазного дефолту там немає.

01.09.2026 воно жило в чотирьох: `canonical-state.json`, `branch-integration.json`,
аргумент у Makefile, константа в тесті. Після переїзду канону на `main` три лишились
на `work/converge-semantic`, і кожне тихо виносило вирок про інший предмет — сторож
зведення звітував ACCEPTED про дзеркало, застигле на комітах тому.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from canonical_declaration import (  # noqa: E402
    REGISTRY,
    CanonicalDeclarationMissing,
    canonical_branch,
)


def test_the_declaration_comes_from_the_state_registry() -> None:
    declared = json.loads((ROOT / REGISTRY).read_text(encoding="utf-8"))["canonical_branch"]
    assert canonical_branch(ROOT) == declared


def test_the_named_branch_actually_exists_in_this_repository() -> None:
    """Оголошення, яке нічого не називає в реальності, гірше за відсутнє."""
    import subprocess

    branches = subprocess.run(
        ["git", "-C", str(ROOT), "branch", "--format=%(refname:short)"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert canonical_branch(ROOT) in branches


@pytest.mark.parametrize(
    "content",
    ["{}", '{"canonical_branch": ""}', '{"canonical_branch": "   "}', "not json at all"],
)
def test_a_registry_that_names_nothing_refuses_instead_of_guessing(
    tmp_path: Path, content: str
) -> None:
    """Дефолт `"main"` виглядав би нешкідливо й був би найгіршим із можливих.

    Реєстр, який перестав називати канон, читався б тоді як реєстр, що назвав
    правильно, — і саме в той момент, коли канон переїхав.
    """
    (tmp_path / REGISTRY.parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / REGISTRY).write_text(content, encoding="utf-8")

    with pytest.raises(CanonicalDeclarationMissing):
        canonical_branch(tmp_path)


def test_a_registry_that_names_a_branch_is_accepted(tmp_path: Path) -> None:
    """Дуал: читач, який відмовляє завжди, — не читач."""
    (tmp_path / REGISTRY.parent).mkdir(parents=True, exist_ok=True)
    (tmp_path / REGISTRY).write_text('{"canonical_branch": "release/x"}', encoding="utf-8")

    assert canonical_branch(tmp_path) == "release/x"
