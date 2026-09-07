#!/usr/bin/env python3
"""Репродукція кандидата з ВІДДАЛЕНОГО джерела зі свіжими залежностями.

Артефакт `reports/closure/CLEAN_ROOM_REPRODUCTION.json` не мав виробника: його клав
рукою той, хто щойно провів прогін. Документ про прогін і прогін — різні речі, і
різниця між ними невидима за побудовою, поки виробника немає. Цей скрипт є виробником.

Відповідає на питання, якого НЕ ставить `verify-clean-clone`: чи відтворюється коміт
поза цим деревом, цим venv і цією машиною. НЕ є незалежною валідацією — виконавець
той самий, незалежні лише вхід і інтерпретатор.

    reproduce_clean_room.py --remote https://github.com/neuron7x/KORPUS.git --sha <коміт>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
#: ОСНОВА, не архів. Перша редакція тягнула з GitHub — а власний `post-commit` цього
#: дерева називає GitHub «дзеркало-архів: Actions заблоковані білінгом, він нічого не
#: запускає й НІЧОГО НЕ СТВЕРДЖУЄ, лише зберігає». Отже найсильніший позитивний доказ
#: релізу свідчив про відтворюваність АРХІВУ, а не того дерева, яке судить конвеєр.
#: Підміна предмета, знайдена незалежною сесією 06.09.2026.
#: Читається з оголошення, а не оголошується вдруге. Друге оголошення рухомого
#: значення розходиться мовчки — і саме так «основа» тут уже одного разу означала
#: архів. Перейменувати віддаленого замість цього виміряно й ВІДКИНУТО: у
#: `branch-integration.json` 24 імені виду `origin/…`, і жодне не існує на форжі
#: сьогодні; усі 24 описують минуле, і перейменування зробило б їх хибними.
FORGES = json.loads((ROOT / "config/operations/forges.json").read_text(encoding="utf-8"))
TRUNK = FORGES["forges"]["trunk"]["url"]
ARCHIVE = FORGES["forges"]["archive"]["url"]


def forge_class(remote: str) -> str:
    """Роль форжа за URL, а не за іменем віддаленого в чиємусь клоні.

    Ім'я `origin` у цьому дереві вказує на АРХІВ. Хто судить за іменем — судить за
    тим, як хтось назвав віддаленого в себе; хто судить за URL — за тим, чим форж є.
    Приймає обидві форми, http і ssh, бо в клоні може стояти будь-яка.
    """
    for role, declared in FORGES["forges"].items():
        if remote in (declared["url"], declared.get("ssh")):
            return str(role).upper()
    return "OTHER"


OUT = "reports/closure/CLEAN_ROOM_REPRODUCTION.json"


def local_remotes_by_role(root: Path) -> dict[str, str]:
    """Які віддалені ЦЬОГО клону несуть яку роль — за URL, не за іменем.

    Заради цього все й робилось. Хто хоче штовхнути в основу, більше не має
    вгадувати, чи `origin` тут означає основу: він питає й дістає ім'я, яке
    в ЦЬОМУ клоні на неї вказує. У каноні відповідь — `{"TRUNK": "gitlab",
    "ARCHIVE": "origin"}`, і саме ця перевернутість півдня водила доказ не туди.
    """
    listed = _run(["git", "-C", str(root), "remote", "-v"], root)
    found: dict[str, str] = {}
    for line in listed.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        role = forge_class(parts[1])
        if role != "OTHER":
            found.setdefault(role, parts[0])
    return found


def _run(
    argv: list[str], cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False, env=env)


def _clone(remote: str, sha: str, tmp: Path) -> Path:
    """Дерево з ВІДДАЛЕНОГО джерела на названому коміті."""
    work = tmp / "tree"
    clone = _run(["git", "clone", "--quiet", remote, str(work)], tmp)
    if clone.returncode:
        raise SystemExit(f"клон із {remote} не вдався: {clone.stderr[-500:]}")
    checkout = _run(["git", "checkout", "--quiet", sha], work)
    if checkout.returncode:
        raise SystemExit(f"коміта {sha} немає на віддаленому: {checkout.stderr[-400:]}")
    return work


def _fresh_environment(work: Path) -> tuple[Path, str]:
    """Свіжий venv із дев-лока ЗА ХЕШАМИ. Повертає інтерпретатор і походження локу."""
    venv = work / ".venv"
    _run([sys.executable, "-m", "venv", str(venv)], work)
    python = venv / "bin/python"
    lock = work / "apps/api/requirements.dev.lock"
    install = _run(
        [str(python), "-m", "pip", "install", "--quiet", "--require-hashes", "-r", str(lock)], work
    )
    if install.returncode:
        raise SystemExit(f"установлення з лока не вдалось: {install.stderr[-800:]}")
    return python, hashlib.sha256(lock.read_bytes()).hexdigest()


def _counts(junit: Path) -> dict[str, int]:
    """Числа з JUnit XML, а не з тексту.

    Підсумковий рядок pytest у цьому оточенні не друкувався взагалі, і розбір тексту
    мовчки давав нуль тестів: «нічого не впало» і «нічого не бігало» виглядали однаково.
    """
    suite = ElementTree.parse(junit).getroot()
    suite = suite if suite.tag == "testsuite" else suite[0]
    total, skipped = int(suite.get("tests", "0")), int(suite.get("skipped", "0"))
    return {
        "tests": total - skipped,
        "failures": int(suite.get("failures", "0")),
        "errors": int(suite.get("errors", "0")),
        "skipped": skipped,
    }


def _battery(work: Path, python: Path) -> tuple[int, dict[str, int]]:
    junit = work / "clean-room-junit.xml"
    completed = _run(
        [
            str(python),
            "-m",
            "pytest",
            "apps/api/tests",
            "-q",
            "--no-cov",
            "-p",
            "no:cacheprovider",
            f"--junitxml={junit}",
        ],
        work,
        env={
            **os.environ,
            "PATH": f"{python.parent}:/usr/bin:/bin",
            "HOME": str(work),
            "PYTHONPATH": str(work / "apps/api/src"),
        },
    )
    if completed.returncode:
        print(completed.stdout[-4000:], file=sys.stderr)
    return completed.returncode, _counts(junit)


def _digest_of(work: Path, python: Path) -> str:
    """Дайджест рахує інтерпретатор КЛОНА над клоном — інакше це вимір цього дерева."""
    measured = _run(
        [
            str(python),
            "-c",
            "import sys;sys.path.insert(0,'apps/api/src');"
            "from korpus.application.provenance import compute_source_digest;"
            "from pathlib import Path;print(compute_source_digest(Path('.')))",
        ],
        work,
    )
    return measured.stdout.strip()


def reproduce(remote: str, sha: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="korpus-clean-room-") as tmp:
        work = _clone(remote, sha, Path(tmp))
        python, freeze = _fresh_environment(work)
        exit_code, pytest_block = _battery(work, python)
        source_digest = _digest_of(work, python)
    return {
        "schema": "korpus.clean-room-remote.v1",
        "class": "REMOTE_SOURCE_FRESH_DEPENDENCIES",
        "distinguishes_from": (
            "verify-clean-clone (клонує з локального ROOT, симлінкує батьківський .venv)"
        ),
        "candidate_sha": sha,
        "environment": "fresh venv from remote clone",
        "dependency_freeze_sha256": freeze,
        "pytest_exit_code": exit_code,
        "pytest": pytest_block,
        "status": "PASS" if exit_code == 0 and pytest_block["tests"] else "FAIL",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_tree_sha256": source_digest,
        "digest_scope": "evidence_paths",
        "release": "v0.9.7",
        "remote": remote,
        "produced_by": "scripts/reproduce_clean_room.py",
        "interpretation": (
            "Репродукція з ВІДДАЛЕНОГО джерела зі свіжими залежностями з локів. Відповідає на "
            "питання, якого не ставить verify-clean-clone: чи відтворюється коміт поза цим "
            "деревом, цим venv і цією машиною. НЕ є незалежною валідацією (L9): виконавець той "
            "самий, незалежні лише вхід і інтерпретатор."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", default=TRUNK)
    parser.add_argument(
        "--also",
        default=None,
        help="другий форж: збіг дайджестів двох незалежних джерел — окрема вісь",
    )
    parser.add_argument("--sha", required=True)
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args()
    payload = reproduce(args.remote, args.sha)
    payload["remote_class"] = forge_class(args.remote)
    if args.also:
        # Незалежність ВХОДУ, а не інтерпретатора: два форжі, дві мережеві дороги, один
        # дайджест. Якщо вони розійшлися — дзеркала несуть різні дерева під одним іменем.
        mirror = reproduce(args.also, args.sha)
        payload["mirror"] = {
            "remote": args.also,
            "source_tree_sha256": mirror["source_tree_sha256"],
            "status": mirror["status"],
            "digests_agree": mirror["source_tree_sha256"] == payload["source_tree_sha256"],
        }
        if not payload["mirror"]["digests_agree"]:
            payload["status"] = "FAIL"
    path = ROOT / args.out
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
