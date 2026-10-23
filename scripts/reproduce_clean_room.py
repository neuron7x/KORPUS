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

ROOT = Path(__file__).resolve().parents[1]
#: ОСНОВА й архів читаються з оголошення, а не вшиваються вдруге. Ролі змінились
#: 19.10.2026 після повного аудиту локального DAG, GitHub і GitLab: GitHub став
#: канонічним форжем, GitLab — спадковим архівом. URL є стабільним предметом доказу;
#: локальне ім'я remote ним не є.
FORGES = json.loads((ROOT / "config/operations/forges.json").read_text(encoding="utf-8"))
TRUNK = FORGES["forges"]["trunk"]["url"]
ARCHIVE = FORGES["forges"]["archive"]["url"]

from clean_room_contract import isolated_git_environment  # noqa: E402
from clean_room_publication import git_config, publish  # noqa: E402
from clean_room_runner import TEST_ARGS, collection_digest, run_battery  # noqa: E402
from trusted_system_tools import git_executable  # noqa: E402


def forge_class(remote: str) -> str:
    """Роль форжа за URL, а не за іменем віддаленого в чиємусь клоні.

    Хто судить за іменем — судить за тим, як хтось назвав віддаленого в себе; хто
    судить за URL — за оголошеною роллю форжа.
    Приймає обидві форми, http і ssh, бо в клоні може стояти будь-яка.
    """
    for role, declared in FORGES["forges"].items():
        if remote in (declared["url"], declared.get("ssh")):
            return str(role).upper()
    return "OTHER"


OUT = "reports/closure/CLEAN_ROOM_REPRODUCTION.json"


def local_remotes_by_role(root: Path) -> dict[str, str]:
    """Які віддалені ЦЬОГО клону несуть яку роль — за URL, не за іменем.

    Хто хоче звернутись до основи, не вгадує значення `origin`: інструмент читає URL
    кожного remote і зіставляє його з єдиним оголошенням ролей.
    """
    git = git_executable()
    if git is None:
        return {}
    listed = _run([git, "-C", str(root), "remote", "-v"], root)
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
    git = git_executable()
    if git is None:
        raise SystemExit("trusted git executable is required for clean-room reproduction")
    work = tmp / "tree"
    env = isolated_git_environment(tmp / "git-home")
    clone = _run([git, "clone", "--quiet", "--", remote, str(work)], tmp, env=env)
    if clone.returncode:
        raise SystemExit(f"клон із {remote} не вдався: {clone.stderr[-500:]}")
    checkout = _run([git, "checkout", "--quiet", sha], work, env=env)
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


def reproduce(remote: str, sha: str) -> tuple[dict[str, Any], bytes]:
    with tempfile.TemporaryDirectory(prefix="korpus-clean-room-") as tmp:
        work = _clone(remote, sha, Path(tmp))
        python, freeze = _fresh_environment(work)
        exit_code, pytest_block, junit, nodeids = run_battery(work, python)
        source_digest = _digest_of(work, python)
    complete = pytest_block["tests"] + pytest_block["skipped"] == len(nodeids)
    return {
        "schema": "korpus.clean-room-remote.v2",
        "class": "REMOTE_SOURCE_FRESH_DEPENDENCIES",
        "distinguishes_from": (
            "verify-clean-clone (клонує з локального ROOT, симлінкує батьківський .venv)"
        ),
        "candidate_sha": sha,
        "environment": "fresh venv from remote clone",
        "dependency_freeze_sha256": freeze,
        "pytest_exit_code": exit_code,
        "pytest": pytest_block,
        "pytest_args": list(TEST_ARGS),
        "collection_nodeids": nodeids,
        "collection_count": len(nodeids),
        "collection_digest": collection_digest(nodeids),
        "status": "PASS" if exit_code == 0 and complete and pytest_block["tests"] else "FAIL",
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
    }, junit


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
    parser.add_argument("--signer", default=None)
    parser.add_argument("--signing-key", default=None)
    args = parser.parse_args()
    payload, junit = reproduce(args.remote, args.sha)
    payload["remote_class"] = forge_class(args.remote)
    mirror: tuple[dict[str, Any], bytes] | None = None
    if args.also:
        mirror_payload, mirror_junit = reproduce(args.also, args.sha)
        mirror = (mirror_payload, mirror_junit)
    publish(
        ROOT,
        args.out,
        payload,
        junit,
        args.signer or git_config(ROOT, "user.email"),
        args.signing_key or git_config(ROOT, "user.signingkey"),
        mirror,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
