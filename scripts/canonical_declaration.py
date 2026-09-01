"""Єдине місце, де читається ім'я канонічної гілки.

01.09.2026 воно було оголошене в ЧОТИРЬОХ місцях: `canonical-state.json`,
`branch-integration.json`, аргументом у Makefile і константою в тесті. Після
переїзду канону на `main` три з них лишились на `work/converge-semantic`, і
кожне тихо давало свій вирок про інший предмет: сторож зведення звітував
ACCEPTED про дзеркало, застигле на комітах тому, а гейт канонічного стану
шукав гілку, яку вже видалено.

Тому тут функція, а не константа: константу скопіюють, функцію — ні.
"""

from __future__ import annotations

import json
from pathlib import Path

REGISTRY = Path("config/operations/canonical-state.json")


class CanonicalDeclarationMissing(RuntimeError):
    """Реєстр не називає канонічної гілки. Здогад тут гірший за відмову."""


def canonical_branch(root: Path) -> str:
    """Ім'я канонічної гілки з реєстру стану. Без дефолту — і це навмисно.

    Дефолт `"main"` виглядав би нешкідливо й був би найгіршим із можливих: реєстр,
    який перестав називати канон, читався б як реєстр, що назвав правильно.
    """
    path = root / REGISTRY
    try:
        declared = json.loads(path.read_text(encoding="utf-8"))["canonical_branch"]
    except (OSError, ValueError, KeyError) as error:
        raise CanonicalDeclarationMissing(f"{path} не називає канонічної гілки") from error
    if not isinstance(declared, str) or not declared.strip():
        raise CanonicalDeclarationMissing(f"{path}: canonical_branch порожній")
    return declared
