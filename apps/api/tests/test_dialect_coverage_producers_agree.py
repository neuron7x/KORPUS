"""Два виробники одного звіту мусять СХОДИТИСЬ — і це має бути виміряно, не обіцяно.

`var/coverage-postgres.json` пише джоб `api:postgres-and-restore` у CI. Локального
виконавця не було ЖОДНОГО: `run_postgres_suite.sh` іде з `--no-cov` навмисно, бо міряє
поведінку. Наслідок виміряно 08.09.2026 — після будь-якої зміни джерела `coverage-union`
порівнював свіжий звіт SQLite зі СТАРИМ звітом постгреса й відмовляв: «прогони описують
різні дерева». Відмова читається як регрес покриття, а каже «тут нема виробника».

`scripts/run_postgres_coverage.sh` цю дірку закриває — і одразу відкриває іншу: двоє
пишуть один артефакт, і розійтись вони можуть мовчки. Тому нижче не «один виробник», а
згода двох, перевірена на кожному прогоні. Різницю, яка ЛЕГІТИМНА, названо окремо: базу
в CI дає служба конвеєра, а локально — контейнер, і цим вони й мусять відрізнятися.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CI = ROOT / ".gitlab-ci.yml"
LOCAL = ROOT / "scripts/run_postgres_coverage.sh"
JOB = "api:postgres-and-restore"

#: Прапорці, від яких залежить САМ ПРЕДМЕТ звіту. Розходження в будь-якому означає, що
#: два файли з одним іменем описують різні речі.
SHARED_FLAGS = ("--cov=apps/api/src/korpus", "--cov-branch", "--cov-fail-under=0")


def _ci_job_lines(job: str) -> list[str]:
    lines = CI.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    in_job = False
    in_script = False
    for line in lines:
        if re.match(rf"^{re.escape(job)}\s*:\s*$", line):
            in_job = True
            continue
        if in_job and re.match(r"^\S", line):
            break
        if in_job and re.match(r"^\s+script\s*:\s*$", line):
            in_script = True
            continue
        if in_job and in_script:
            if re.match(r"^\s{2}\S", line):
                in_script = False
                continue
            out.append(line.strip().lstrip("- ").strip())
    return out


def _ci_pytest_line() -> str:
    lines = [line for line in _ci_job_lines(JOB) if "pytest" in line and "apps/api/tests" in line]
    assert lines, f"джоб {JOB} більше не ганяє набір"
    return lines[0]


def test_both_producers_write_the_report_the_union_reads() -> None:
    """Половина союзу — це звіт SQLite у чужому імені."""
    assert "var/coverage-postgres.json" in _ci_pytest_line()
    assert "var/coverage-postgres.json" in LOCAL.read_text(encoding="utf-8")


def test_the_two_producers_agree_on_what_they_measure() -> None:
    ci_line = _ci_pytest_line()
    local = LOCAL.read_text(encoding="utf-8")
    divergent = [flag for flag in SHARED_FLAGS if (flag in ci_line) != (flag in local)]
    assert not divergent, (
        f"виробники розійшлись у прапорцях покриття: {divergent} — два файли з одним "
        "іменем описували б різні речі"
    )


def test_neither_producer_disables_coverage() -> None:
    """`--no-cov` тут — не дрібниця стилю: він робить звіт порожнім, лишаючи імʼя."""
    assert "--no-cov" not in _ci_pytest_line()
    local_run = [
        line
        for line in LOCAL.read_text(encoding="utf-8").splitlines()
        if "pytest" in line and "apps/api/tests" in line
    ]
    assert local_run, "локальний виробник більше не ганяє набір"
    assert all("--no-cov" not in line for line in local_run)


def test_the_local_producer_refuses_instead_of_skipping_without_docker() -> None:
    """Тихо не побігти означало б лишити старий звіт і назвати його свіжим виміром."""
    text = LOCAL.read_text(encoding="utf-8")
    assert "command -v docker" in text
    assert "exit 2" in text


def _assigned(text: str, name: str) -> str:
    """Значення ПРИСВОЄННЯ, а не будь-яка поява рядка у файлі.

    Перша редакція цього тесту шукала «55433» по всьому тексту й почервоніла на слові в
    КОМЕНТАРІ, який пояснював, чому цей порт узятий чужим. Той самий клас уже ловився на
    правилі, що матчило слово в echo-коментарі: сторож мусить дивитись на виконуваний
    токен.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped.startswith(f"{name}="):
            continue
        return stripped.split("=", 1)[1].strip().strip('"')
    raise AssertionError(f"присвоєння {name}= не знайдено")


def test_the_local_producer_does_not_collide_with_the_behaviour_suite() -> None:
    """Гейт постгреса не реентерабельний: два прогони зносять контейнер одне одному."""
    behaviour = (ROOT / "scripts/run_postgres_suite.sh").read_text(encoding="utf-8")
    local = LOCAL.read_text(encoding="utf-8")
    assert _assigned(behaviour, "container") != _assigned(local, "container"), (
        "локальний виробник узяв чуже імʼя контейнера"
    )
    assert _assigned(behaviour, "port") != _assigned(local, "port"), (
        "локальний виробник узяв чужий порт"
    )
    assert _assigned(behaviour, "database") != _assigned(local, "database"), (
        "локальний виробник узяв чужу базу"
    )
