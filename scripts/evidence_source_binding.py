#!/usr/bin/env python3
"""Прив'язати живі докази забезпечення до байтів, ЗАКОМІЧЕНИХ у git.

Виміряно 01.09.2026: одна правка розводить дайджест РОБОЧОГО дерева з HEAD
(e4c4d94295e72fde21477e33 проти 9c1960c0158310dca0b694e1).
Ніщо в дереві цієї розбіжності не питало. Отже звіт про забезпечення міг бути
виданий, підписаний і опублікований із `source_digest`, якого немає в ЖОДНОМУ
коміті: пізніше його неможливо відтворити, бо байти, які він описує, існували
лише в робочому дереві, якого вже немає. Це не «застарілий доказ» — це доказ
про стан, до якого не можна повернутись.

Дайджест коміту й дерева рахує ТА САМА `digest_source_records`: друга реалізація
розійшлася б на першому уточненні правила.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from trusted_system_tools import git_environment, git_executable

ROOT = Path(__file__).resolve().parents[1]
APP_SRC = ROOT / "apps/api/src"
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from korpus.application.provenance import (  # noqa: E402
    EVIDENCE_SOURCE_PATHS,
    digest_source_records,
    evidence_source_path_included,
)


def _git(root: Path, *args: str) -> bytes:
    if (executable := git_executable()) is None:
        raise FileNotFoundError("trusted Git executable unavailable")
    return subprocess.run(
        [executable, "--no-replace-objects", *args],
        cwd=root,
        env=git_environment(),
        check=True,
        capture_output=True,
    ).stdout


def committed_evidence_source_digest(ref: str = "HEAD", root: Path = ROOT) -> str:
    """Канонічний дайджест доказової поверхні з ЗАКОМІЧЕНОГО git-посилання."""
    try:
        listing = _git(
            root, "ls-tree", "-r", "-z", "--name-only", ref, "--", *EVIDENCE_SOURCE_PATHS
        ).split(b"\0")
        names = sorted(
            {
                raw.decode("utf-8")
                for raw in listing
                if raw and evidence_source_path_included(raw.decode("utf-8"))
            }
        )
        records = ((name, _git(root, "show", f"{ref}:{name}")) for name in names)
        return digest_source_records(records)
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise RuntimeError(f"cannot read evidence-bearing source from git ref {ref!r}") from error


def evidence_source_binding_failure(
    claimed_digest: object, ref: str = "HEAD", root: Path = ROOT
) -> str | None:
    """Причина відмови, коли доказ не прив'язаний до закоміченого джерела; інакше None.

    Форма помилки названа ОКРЕМО від розбіжності: «дайджест відсутній» і «дайджест
    не збігається» — різні стани, і злиття їх в один рядок зробило б відсутність
    невідрізненною від підміни.
    """
    if not isinstance(claimed_digest, str) or len(claimed_digest) != 64:
        return "assurance evidence source digest is missing or malformed"
    try:
        int(claimed_digest, 16)
    except ValueError:
        return "assurance evidence source digest is missing or malformed"
    try:
        actual = committed_evidence_source_digest(ref=ref, root=root)
    except RuntimeError:
        return "assurance evidence source digest cannot be verified against committed HEAD"
    if claimed_digest.lower() != actual:
        return "assurance evidence source digest does not match committed HEAD"
    return None


def main() -> int:
    import json

    payload = {
        "schema": "korpus.evidence-source-binding.v1",
        "ref": "HEAD",
        "committed_digest": committed_evidence_source_digest(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
