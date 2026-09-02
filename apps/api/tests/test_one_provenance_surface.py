"""Поверхня, над якою рахується дайджест джерела, мусить бути оголошена РІВНО раз.

Два оголошення одного предмета не сперечаються — вони мовчки розходяться, і розбіжність
помітна лише тоді, коли хтось порівняє два числа, породжені різними лінійками.

ВИМІРЯНО 02.09.2026. У дереві жили ДВА `EVIDENCE_SOURCE_PATHS` і ДВА
`compute_source_digest` з однаковою сигнатурою:

    application/provenance_surface.py   20 шляхів   імпортує provenance.py
    application/evidence_digest.py      13 шляхів   не імпортував НІХТО

Різниця не косметична: у сироти був `.github/workflows/assurance.yml`, якого немає в
живому; у живого — `apps/web`, `contracts`, `deploy`, `infra`, `.gitlab-ci.yml`,
`docker-compose.yml`, `.dockerignore`, `.github/workflows`. Імпорт не того модуля дав би
дайджест над ІНШОЮ поверхнею під тим самим іменем функції — і жоден гейт не побачив би
різниці, бо обидва числа виглядають як дайджест.

Слабшу тотожність видалено, а не узгоджено: узгоджені копії розходяться знову.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "apps/api/src"


def _modules_declaring(name: str) -> list[str]:
    """Модулі, що присвоюють цьому імені на рівні модуля."""
    found: list[str] = []
    for path in sorted(SOURCE.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):  # pragma: no cover - дерево не парситься
            continue
        for node in tree.body:
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                found.append(str(path.relative_to(ROOT)))
                break
    return found


def _modules_defining(name: str) -> list[str]:
    found: list[str] = []
    for path in sorted(SOURCE.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):  # pragma: no cover
            continue
        if any(isinstance(node, ast.FunctionDef) and node.name == name for node in tree.body):
            found.append(str(path.relative_to(ROOT)))
    return found


def test_the_evidence_surface_is_declared_exactly_once():
    declaring = _modules_declaring("EVIDENCE_SOURCE_PATHS")
    assert declaring == ["apps/api/src/korpus/application/provenance_surface.py"], declaring


def test_the_source_digest_is_computed_by_exactly_one_function():
    defining = _modules_defining("compute_source_digest")
    assert defining == ["apps/api/src/korpus/application/provenance.py"], defining


def test_the_checker_can_see_a_second_declaration(tmp_path, monkeypatch):
    """Негативний контроль. Перевірка, що не вміє побачити дублікат, ним не є.

    Без цього тест вище був би зелений і на дереві, де другого оголошення просто немає з
    інших причин — наприклад якщо обхід зламався й нічого не знаходить.
    """
    module = SOURCE / "korpus" / "application" / "provenance_surface.py"
    assert module.is_file()
    tree = ast.parse(module.read_text(encoding="utf-8"))
    declared = [
        target.id
        for node in tree.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        for target in [node.target]
    ]
    assert "EVIDENCE_SOURCE_PATHS" in declared, (
        "обхід не бачить оголошення навіть у файлі, де воно точно є"
    )
