"""Документ, що називає файл, якого немає, — не помилка форматування.

ВИМІРЯНО 02.09.2026. `docs/audit/DESTRUCTION_STAGE_2026-08-05.md` подавав числа —
«73×», «882 недоставлені контрольні точки», таблицю подій за секунду — і називав
джерелом кожного виміру три скрипти: `attack_span_listing.py`, `attack_anchor_backlog.py`,
`attack_audit_throughput.py`. Жоден не існував НІКОЛИ (`git log --all --diff-filter=A`
порожній для всіх трьох), і скриптів атак у дереві немає взагалі. Стадія руйнування,
обов'язкова перед злиттям, мала звіт із числами й не мала інструмента.

Тести тримають ФОРМУ ліків, а не лише результат. Форма мала три ітерації, і кожну зняв
ЗАПУСК, не міркування:

  * дослівне порівняння шляхів дало 242 знахідки на 242 — документи законно пишуть
    `composition.py` замість повного шляху. Звідси розв'язання скорочень за суфіксом;
  * реєстр виправдань створив би збочений стимул: написати «X прибрано» ставало б
    дорожче, ніж змовчати. Звідси маркер у САМОМУ тексті;
  * гейт спирався на `git ls-files`, а проба живучості копіює дерево БЕЗ `.git` — і
    червонів би в чистому клоні, у продакшенному образі й у пісочниці. Звідси опис із
    трьох ярусів і окремий, ШИРШИЙ обсяг розв'язання.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "document_references", ROOT / "scripts/check_document_references.py"
)
assert _SPEC and _SPEC.loader
gate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gate)


def test_a_named_file_that_does_not_exist_is_a_failure():
    verdict = gate.assess([{"document": "d.md", "reference": "ghost.py"}], 12)
    assert verdict["status"] == "FAIL"
    assert "ghost.py" in verdict["problems"][0]


def test_a_tree_without_a_description_is_unknown_not_pass():
    """«Не знаю, що в дереві» ≠ «в дереві нічого немає»."""
    assert gate.assess(None, 12)["status"] == "UNKNOWN"
    assert gate._inventory(Path("/nonexistent")) is None


def test_zero_documents_is_unknown_not_pass():
    assert gate.assess([], 0)["status"] == "UNKNOWN"


def test_abbreviations_resolve_by_path_suffix():
    """Без цього перевірка кричить вовк на 242 місцях із 242."""
    tracked = ["apps/api/src/korpus/application/composition.py"]
    assert gate._resolves("composition.py", tracked, Path("/nonexistent"))
    assert not gate._resolves("ghost.py", tracked, Path("/nonexistent"))
    # Хвіст мусить збігатися по МЕЖІ теки, інакше `sition.py` розв'язалось би.
    assert not gate._resolves("sition.py", tracked, Path("/nonexistent"))


def test_the_text_itself_excuses_what_it_says_is_gone():
    """Реєстр виправдань зробив би правду про видалене дорожчою за мовчання."""
    assert gate._GONE.search("`REPOSITORY_MANIFEST.json` ВИДАЛЕНО з дерева")
    assert not gate._GONE.search("Відтворено (`attack_span_listing.py`): 73x")


def test_a_document_banner_excuses_the_whole_document():
    assert gate._excused_document(
        "# Х\n\n> ## 🔴 ЧИСЛА НЕ МАЮТЬ ПІДСТАВИ: інструментів не існувало\n"
    )
    assert not gate._excused_document("# Х\n\nЗвичайний текст із `ghost.py`.\n")


def test_run_artifacts_are_not_judged_but_are_still_resolved():
    """Обсяг СУДЖЕННЯ вузький, обсяг РОЗВ'ЯЗАННЯ широкий — це різні рішення."""
    assert "var/recovery-report.json".startswith(gate._GENERATED)
    assert not "docs/x.md".startswith(gate._GENERATED)
    assert "handoff/evidence/current/MANIFEST.json" in gate._on_disk(ROOT)


def test_observe_finds_a_dead_reference_in_a_fixture_tree(tmp_path: Path):
    """Обхід дерева, не лише вирок над готовим списком.

    Перша версія цих тестів перевіряла лише `assess()` із синтетичним переліком, і мутант
    M627 — той, що прибирає саму перевірку в `observe()` — ВИЖИВ: тест не проходив
    дорогою, яку мутували. Проба мусить рухати той вхід, про який твердження.
    """
    (tmp_path / "SOURCE_MANIFEST.json").write_text(
        json.dumps({"files": [{"path": "real.py"}]}), encoding="utf-8"
    )
    (tmp_path / "real.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "doc.md").write_text(
        "# Проба\n\nВідтворено (`phantom_probe.py`): 41x.\n", encoding="utf-8"
    )
    dead = gate.observe(tmp_path)
    assert dead is not None
    assert [item["reference"] for item in dead] == ["phantom_probe.py"]

    (tmp_path / "doc.md").write_text("# Проба\n\nВідтворено (`real.py`): 41x.\n", encoding="utf-8")
    assert gate.observe(tmp_path) == []


def test_the_tree_itself_has_no_dead_reference():
    """Негативний контроль на живому дереві: гейт мусить бути зелений ТУТ і зараз."""
    verdict = gate.assess(gate.observe(ROOT), len(gate.documents(ROOT)))
    assert verdict["status"] == "PASS", json.dumps(verdict["problems"][:5], ensure_ascii=False)
