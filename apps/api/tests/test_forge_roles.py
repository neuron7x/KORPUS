"""Роль форжа за URL, а не за іменем віддаленого.

Ім'я `origin` у цьому дереві вказує на АРХІВ — так склалось історично. Півдня доказ
репродукції знімався саме з нього, бо дефолт вів туди, а власний `post-commit` цього ж
дерева називає GitHub «дзеркало-архів, який нічого не стверджує».

Очевидне виправлення — перейменувати `origin` на GitLab — виміряно і ВІДКИНУТО:
`config/operations/branch-integration.json` містить 24 імені виду `origin/…`, і ЖОДНЕ
не існує на форжі сьогодні. Усі 24 описують минуле; перейменування зробило б їх
хибними твердженнями про те, чого не було. Замість переписувати минуле — назвали ролі
за URL, який не залежить від того, як хтось назвав віддаленого у своєму клоні.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DECLARATION = ROOT / "config/operations/forges.json"


def _module():
    spec = importlib.util.spec_from_file_location("rcr", ROOT / "scripts/reproduce_clean_room.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_role_follows_the_url_not_the_remote_name() -> None:
    module = _module()
    declared = json.loads(DECLARATION.read_text(encoding="utf-8"))["forges"]

    for role, forge in declared.items():
        assert module.forge_class(forge["url"]) == role.upper()
        assert module.forge_class(forge["ssh"]) == role.upper()

    # Невідомий форж НЕ мовчить і НЕ вгадується як основа.
    assert module.forge_class("https://example.invalid/x.git") == "OTHER"


def test_the_declaration_is_not_repeated_in_code() -> None:
    """Друге оголошення рухомого значення розходиться мовчки.

    Саме так «основа» тут одного разу вже означала архів: URL стояв у скрипті, і
    ніхто не звіряв його з тим, який форж справді судить.
    """
    declared = json.loads(DECLARATION.read_text(encoding="utf-8"))["forges"]
    urls = {f["url"] for f in declared.values()} | {f["ssh"] for f in declared.values()}

    repeated: list[str] = []
    for path in sorted((ROOT / "scripts").glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for url in urls:
            if url in text and path.name != "reproduce_clean_room.py":
                repeated.append(f"{path.name}: {url}")

    assert repeated == [], (
        "URL форжа оголошено вдруге поза `config/operations/forges.json` — "
        f"це друга тотожність, і вона розійдеться мовчки: {repeated}"
    )


def test_local_remotes_are_described_not_assumed(tmp_path: Path) -> None:
    """Умову СТВОРЕНО, не успадковано: клон із локальним шляхом ролей не має.

    Без цього твердження тест був би зеленим у дереві, де віддалених немає взагалі,
    і нічого б не доводив.
    """
    module = _module()

    empty = module.local_remotes_by_role(tmp_path)
    assert empty == {}, "тека без git не сміє віддавати ролі"

    canon = ROOT
    roles = module.local_remotes_by_role(canon)
    if not roles:
        import pytest

        pytest.skip("це дерево не має віддалених на оголошені форжі: вісь не вимірна тут")

    # Перевернутість НАЗВАНА, а не виправлена: інструмент питає й дістає відповідь.
    assert set(roles) <= {"TRUNK", "ARCHIVE"}
    for role, remote in roles.items():
        assert remote, f"{role}: ім'я віддаленого порожнє"
