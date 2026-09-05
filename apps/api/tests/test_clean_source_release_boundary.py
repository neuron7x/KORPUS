from __future__ import annotations

from pathlib import Path

from scripts.manifest_paths import source_included

ROOT = Path(__file__).resolve().parents[3]


def test_package_producer_excludes_git_history_by_construction() -> None:
    producer = (ROOT / "scripts/package_repository.sh").read_text(encoding="utf-8")
    assert "git bundle" not in producer
    assert 'git archive --format=tar "$source_commit"' in producer
    assert '"history_included":false' in producer
    assert "git rev-parse HEAD" in producer


def test_only_formal_production_promotion_requires_the_release_tag() -> None:
    producer = (ROOT / "scripts/package_repository.sh").read_text(encoding="utf-8")
    promotion = (ROOT / "scripts/package_production_release.sh").read_text(encoding="utf-8")
    assert "check_release_identity.py --require-git-tag" not in producer
    assert "check_release_identity.py --require-git-tag" in promotion


def test_package_only_metadata_cannot_expand_source_authority() -> None:
    for path in (
        "PACKAGE_BUILD.json",
        "FULL_SSOT_PACKAGE_RECEIPT.json",
        "PACKAGE_BOUNDARY.md",
        "CANONICAL_RELEASE_REPORT.json",
        "reports/RESEARCH_ASSURANCE_REPORT.json",
        "evidence/sealed.json",
    ):
        assert source_included(Path(path)) is False
    assert source_included(Path("docs/PACKAGE_BUILD.json")) is True


def test_release_evidence_verification_cannot_be_skipped_by_an_environment_variable() -> None:
    """Виклик перевіряльника доказів мусить бути БЕЗУМОВНИЙ, не «за замовчуванням».

    До 05.09.2026 `KORPUS_ENGINEERING_CANDIDATE=1` вів у гілку, яка цей виклик минала
    і брала дозвіл із двох полів `CANONICAL_RELEASE_REPORT.json` — файла, якого не пише
    жоден крок. Гейт питав дозволу в оголошення, що лежить поруч із ним у тому самому
    дереві, тож був зелений рівно в тому стані, заради якого існує.

    Перевіряється СТРУКТУРА, не написання: рядок із викликом мусить стояти на нульовому
    відступі, тобто поза будь-яким `if`/`case`. Отрута, яка вбиває цей контроль, —
    засунути виклик під умову: відступ зросте і твердження впаде. Контроль НЕ доводить,
    що перевіряльник щось знаходить; він доводить лише, що його не можна обійти вимкненням.
    """
    producer = (ROOT / "scripts/package_repository.sh").read_text(encoding="utf-8")
    calls = [line for line in producer.splitlines() if "verify_release_evidence.py" in line]
    assert calls, "пакувальник мусить взагалі викликати перевіряльник доказів"
    for line in calls:
        assert line == line.lstrip(), f"виклик під умовою — його можна обійти: {line!r}"
    code = [line for line in producer.splitlines() if not line.lstrip().startswith("#")]
    assert not [line for line in code if "KORPUS_ENGINEERING_CANDIDATE" in line], (
        "змінна лишилась ВИКОНУВАНОЮ, а не спогадом у коментарі"
    )
