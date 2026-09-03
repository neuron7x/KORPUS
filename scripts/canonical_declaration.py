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
import subprocess
from pathlib import Path

REGISTRY = Path("config/operations/canonical-state.json")

#: Робоче дерево з іменованими гілками — те, про яке оголошення взагалі щось каже.
CANONICAL_WORKSPACE = "CANONICAL_WORKSPACE"
#: Чекаут конвеєра: відчеплена голова, гілок немає. Тут ПРЕДМЕТА оголошення немає.
EPHEMERAL_CHECKOUT = "EPHEMERAL_CHECKOUT"


def workspace_kind(root: Path) -> str:
    """Яке це дерево — за ФАКТОМ, не за змінною оточення.

    Виміряно 02.09.2026 в конвеєрі: три перевірки канону впали не тому, що канон
    зламався, а тому, що GitLab робить чекаут на відчепленій голові без жодної
    локальної гілки. Твердження «оголошена гілка існує в цьому репозиторії» там не
    хибне — воно ПРО ІНШИЙ ПРЕДМЕТ, якого в чекауті немає.

    Ознака одна й перевіряється, а не вгадується: чи має репозиторій ГІЛКИ під
    `refs/heads`. Змінна `CI_*` сказала б, ДЕ ми, а не ЩО в дереві; дерево з гілками
    лишається канонічним і всередині конвеєра, і перевірки там мусять виконатись.

    Береться `for-each-ref`, а не `git branch`: другий друкує ще й псевдорядок
    «(HEAD detached at …)», і клон із відчепленою головою виглядав би через нього як
    дерево з гілкою. Саме цей рядок стояв у падінні конвеєра 02.09.2026:
    `assert 'main' in ['(HEAD', 'detached', 'at', '9a0dfc5)']`.
    """
    done = subprocess.run(
        ["git", "-C", str(root), "for-each-ref", "--format=%(refname:short)", "refs/heads"],
        capture_output=True,
        text=True,
        check=False,
    )
    return CANONICAL_WORKSPACE if done.stdout.split() else EPHEMERAL_CHECKOUT


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
