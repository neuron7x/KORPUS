"""Сторожі дайджесту походження, яких не запускав жоден прогін.

Вимір покриття гілок 04.09.2026: чотири дуги цього модуля не бралися ані під SQLite,
ані під PostgreSQL. Усі чотири — про те, ЩО входить у підпис і чи можна йому вірити:
порожній перелік відстеженого, файл, що змінився під час хешування, і два правила
виключення поверхні. Дайджест, чиї межі не перевірені, підписує невідомо що.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest
from korpus.application.provenance import (
    ProvenanceError,
    _tracked_paths,
    compute_source_digest,
    evidence_source_path_included,
)


def test_empty_git_listing_falls_through_to_the_manifest(tmp_path: pathlib.Path) -> None:
    """Репозиторій без жодного файла — це «невідомо», а не «відстежено нуль файлів».

    Порожня множина відстеженого зробила б УСІ файли дерева невідстеженими, і
    `_digest_candidates` мовчки відкинув би кожен: дайджест порожнечі замість
    дайджесту джерела. Тому порожній перелік мусить впасти до маніфесту, а за
    його відсутності — сказати «невідомо» через None.
    """
    if subprocess.run(["git", "init", "-q", str(tmp_path)], check=False).returncode != 0:
        pytest.skip("git недоступний — предмет виміру не відтворюється")
    assert _tracked_paths(tmp_path) is None


def test_source_that_changes_size_while_hashing_is_refused(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Розмір із `stat` і кількість прочитаних байтів — два виміри одного файла.

    Якщо вони розходяться, файл змінили ПІД ЧАС читання, і хеш описує стан, якого
    вже немає. Мовчазне повернення такого хеша було б підписом під міражем.
    """

    class _OneByteBigger:
        """Той самий stat, але на байт більший: файл «зменшився» після виміру."""

        def __init__(self, real: object) -> None:
            self._real = real

        def __getattr__(self, name: str) -> object:
            return getattr(self._real, name)

        @property
        def st_size(self) -> int:
            return int(self._real.st_size) + 1  # type: ignore[attr-defined]

    target = tmp_path / "data.txt"
    target.write_bytes(b"evidence bytes")
    real_stat = pathlib.Path.stat

    def lying_stat(self: pathlib.Path, *args: object, **kwargs: object) -> object:
        result = real_stat(self, *args, **kwargs)  # type: ignore[arg-type]
        if self == target:
            return _OneByteBigger(result)
        return result

    monkeypatch.setattr(pathlib.Path, "stat", lying_stat)
    with pytest.raises(ProvenanceError, match="source changed while hashing"):
        compute_source_digest(tmp_path, ["data.txt"])


@pytest.mark.parametrize(
    "relative",
    ["apps/api/src/korpus/__pycache__/models.py", "var/report.json", "apps/api/.venv/x.py"],
)
def test_excluded_directories_are_outside_the_signed_surface(relative: str) -> None:
    """Кеші й `var/` не підписують: їхній вміст залежить від прогону, не від джерела."""
    assert evidence_source_path_included(relative) is False


@pytest.mark.parametrize("relative", ["apps/api/src/korpus/models.pyc", "scripts/tool.pyo"])
def test_compiled_artifacts_are_outside_the_signed_surface(relative: str) -> None:
    """Байткод — похідна від джерела; підписувати його означає підписувати те саме двічі."""
    assert evidence_source_path_included(relative) is False
