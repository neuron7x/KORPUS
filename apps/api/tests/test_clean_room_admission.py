"""Репродукція з чистої кімнати: вісім перевірок, які не читав жоден тест.

`clean_room_checks` додано 06.09.2026 як відповідь на VD-6 («доказ без споживача»).
Мутаційний прогін показав, що інвертувати можна `status_pass`, `class_is_remote` і
`source_bound`, а повна батарея лишається зеленою. Потім чотири перевірки слідів
самого прогону додались — і теж без жодного тесту. Тут кожне плече своє: спочатку
позитивне (артефакт, що ПРОХОДИТЬ), потім по одному спростуванню на перевірку.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.current_truth_admission import CLEAN_ROOM, clean_room_checks

DIGEST = "a" * 64
ALL = (
    "present",
    "status_pass",
    "class_is_remote",
    "source_bound",
    "run_counted",
    "run_clean",
    "names_candidate",
    "names_dependency_origin",
)


def _artefact(root: Path, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "status": "PASS",
        "class": "REMOTE_SOURCE_FRESH_DEPENDENCIES",
        "source_tree_sha256": DIGEST,
        "pytest": {"tests": 3892, "failures": 0, "errors": 0},
        "candidate_sha": "448fb4bc87bf355f47785d956fe6d97e0d9a49ca",
        "dependency_freeze_sha256": "c" * 64,
    }
    payload.update(overrides)
    path = root / CLEAN_ROOM
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return root


def _only(root: Path, digest: str = DIGEST) -> dict[str, bool]:
    return {key.rsplit(".", 1)[1]: value for key, value in clean_room_checks(root, digest).items()}


def test_a_passing_remote_reproduction_of_this_tree_is_admitted(tmp_path: Path) -> None:
    """Позитивне плече. Без нього кожне спростування нижче проходило б і на
    перевірці, що завжди повертає False."""
    checks = _only(_artefact(tmp_path))
    assert set(checks) == set(ALL), "перевірку додано або прибрано без тесту на неї"
    assert all(checks.values())


def test_a_reproduction_that_did_not_pass_is_not_admitted(tmp_path: Path) -> None:
    checks = _only(_artefact(tmp_path, status="FAIL"))
    assert checks["status_pass"] is False
    assert checks["class_is_remote"] is True


def test_a_local_clone_is_not_a_remote_reproduction(tmp_path: Path) -> None:
    """`verify-clean-clone` пише СЛАБШИЙ клас; зарахувати його означало б назвати
    клон із локального дерева репродукцією з віддаленого джерела."""
    checks = _only(_artefact(tmp_path, **{"class": "LOCAL_CLONE"}))
    assert checks["class_is_remote"] is False
    assert checks["status_pass"] is True


def test_a_reproduction_of_another_tree_is_not_source_bound(tmp_path: Path) -> None:
    checks = _only(_artefact(tmp_path, source_tree_sha256="b" * 64))
    assert checks["source_bound"] is False


def test_an_empty_digest_cannot_bind_a_reproduction(tmp_path: Path) -> None:
    """Порожній дайджест дорівнював би сам собі: прив'язка задовольнялась би тим,
    що дайджест не обчислили."""
    checks = _only(_artefact(tmp_path, source_tree_sha256=""), digest="")
    assert checks["source_bound"] is False


def test_a_reproduction_that_ran_nothing_is_not_a_reproduction(tmp_path: Path) -> None:
    """Нуль виконаних тестів і чиста батарея нерозрізненні за `failures == 0`."""
    checks = _only(_artefact(tmp_path, pytest={"tests": 0, "failures": 0, "errors": 0}))
    assert checks["run_counted"] is False
    assert checks["run_clean"] is True, "чистота і наповненість — різні властивості"


def test_a_reproduction_with_failures_is_not_clean(tmp_path: Path) -> None:
    checks = _only(_artefact(tmp_path, pytest={"tests": 12, "failures": 1, "errors": 0}))
    assert checks["run_clean"] is False
    assert checks["run_counted"] is True


def test_a_reproduction_with_collection_errors_is_not_clean(tmp_path: Path) -> None:
    """Помилка збору дає нуль падінь: батарея не впала, вона не почалась."""
    checks = _only(_artefact(tmp_path, pytest={"tests": 12, "failures": 0, "errors": 2}))
    assert checks["run_clean"] is False


def test_a_reproduction_without_a_pytest_block_counts_nothing(tmp_path: Path) -> None:
    checks = _only(_artefact(tmp_path, pytest="3892 passed"))
    assert checks["run_counted"] is False
    assert checks["run_clean"] is False


def test_a_reproduction_that_names_no_candidate_is_about_no_commit(tmp_path: Path) -> None:
    checks = _only(_artefact(tmp_path, candidate_sha=""))
    assert checks["names_candidate"] is False


def test_a_reproduction_that_names_no_dependency_origin_is_not_reproducible(
    tmp_path: Path,
) -> None:
    """Свіжі залежності без названого походження — прогін, який ніхто не повторить."""
    checks = _only(_artefact(tmp_path, dependency_freeze_sha256=""))
    assert checks["names_dependency_origin"] is False


def test_an_absent_reproduction_is_absent_not_silently_fine(tmp_path: Path) -> None:
    assert clean_room_checks(tmp_path, DIGEST) == {f"{CLEAN_ROOM}.present": False}


def test_the_reproduction_names_the_trunk_not_the_archive() -> None:
    """Найсильніший позитивний доказ свідчив про АРХІВ, а не про основу.

    Перша редакція `reproduce_clean_room.py` тягнула з GitHub, а власний `post-commit`
    цього дерева називає GitHub «дзеркало-архів: Actions заблоковані білінгом, він
    нічого не запускає й НІЧОГО НЕ СТВЕРДЖУЄ, лише зберігає». Вирок конвеєра виносить
    GitLab. Отже репродукція доводила відтворюваність не того дерева, яке судять.
    Знайдено незалежною сесією 06.09.2026 — підміна ПРЕДМЕТА, не помилка коду.
    """
    import importlib.util

    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "reproduce_clean_room", root / "scripts/reproduce_clean_room.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert "gitlab.com" in module.TRUNK
    assert "github.com" in module.ARCHIVE
    assert module.TRUNK != module.ARCHIVE
