from __future__ import annotations

from scripts.verify_regression_carry_forward import diff_records


def test_diff_records_classifies_added_removed_and_modified_without_overlap() -> None:
    old = {"same": "a", "modified": "b", "removed": "c"}
    new = {"same": "a", "modified": "d", "added": "e"}
    added, removed, modified = diff_records(old, new)
    assert added == ("added",)
    assert removed == ("removed",)
    assert modified == ("modified",)


def test_diff_records_is_deterministic() -> None:
    old = {"z": "1", "a": "1"}
    new = {"z": "2", "b": "1"}
    assert diff_records(old, new) == (("b",), ("a",), ("z",))


def test_the_verifier_does_not_write_into_the_evidence_it_verifies() -> None:
    """Виміряно 01.09.2026: щоб дізнатись, чи ціль запускається, її запустили — і вона
    перезаписала `reports/release/v0.7.0/REGRESSION_CARRY_FORWARD.json`, той самий
    артефакт, який `build_readiness_947_evidence.py` читає як доказ.

    Перевірка, що пише в те, що перевіряє, робить розбіжність між твердженням і станом
    неспостережною: після прогону вони збігаються завжди. Тому типовий вихід —
    чернетка, і писати в реліз можна лише назвавши шлях явно.
    """
    import re
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[3] / "scripts/verify_regression_carry_forward.py"
    ).read_text(encoding="utf-8")
    matched = re.search(r'"--out",\s*type=Path,\s*default=ROOT\s*/\s*"(?P<path>[^"]+)"', source)
    assert matched is not None, "типовий шлях виходу не знайдено"
    default = matched.group("path")
    assert not default.startswith("reports/"), default
    assert default.startswith("var/"), default
