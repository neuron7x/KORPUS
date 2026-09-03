#!/usr/bin/env python3
"""Виконати впорядкований release-lane зі сталою тотожністю дерева."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.provenance import compute_source_digest  # noqa: E402

#: (ціль, роль). Роль пояснює, чому крок стоїть саме тут, і читається у звіті.
STEPS: tuple[tuple[str, str], ...] = (
    ("evidence-refresh", "маніфест описує це дерево"),
    ("api-test", "виробник"),
    # `assemble-assurance` вимагає var/quality-report.json, і виробляє його ЛИШЕ
    # `api-lint`. Без нього лан проходив тільки там, де файл лишився від чужого
    # прогону: у чистому дереві він падав на збірці доказу, а `check` містить
    # api-lint і про розбіжність двох переліків не питав ніхто. Виміряно 03.09.2026.
    ("api-lint", "виробник"),
    ("mutation", "виробник"),
    ("eval", "виробник"),
    ("migration-gate", "виробник"),
    ("scale", "виробник"),
    ("operational-gate", "споживач: хешує звіти виробників"),
    ("assemble-assurance", "збірка доказу"),
    ("snapshot", "публікація доказу"),
    ("validate", "гейти"),
    ("gate-liveness", "чи гейти здатні почервоніти"),
    ("release-surface", "знаменник не скоротився"),
    ("lane-report", "що виміряно, а що не встигло"),
    ("corpus-axes", "профіль осей"),
)

#: Зовнішні гейти. Ідуть ПІСЛЯ джерела й потребують docker.
EXTERNAL: tuple[tuple[str, str], ...] = (
    ("production-postgres-security", "справжній PostgreSQL"),
    ("production-exact-environment-image", "точний інтерпретатор у продакшенному образі"),
    ("production-hard-predicates", "перелік того, що ще зовні"),
)

#: Кроки, чий доказ виробляє ЛИШЕ зовнішній лан. `assemble-assurance` вимагає
#: `var/recovery-report.json`, який виробляє лише `.gitlab-ci.yml`; локальний лан без
#: docker не досягає PASS. Інакше --skip-external або спинявся, або приймав давній
#: артефакт із var/. Пропуск дістав власне слово й ніколи не дає PASS.
EXTERNAL_EVIDENCE: frozenset[str] = frozenset({"assemble-assurance", "snapshot", "corpus-axes"})

SKIPPED = "SKIPPED_REQUIRES_EXTERNAL"

#: Вирок, коли лан спинився: жодне число далі не про це дерево.
NOT_REACHED: dict[str, Any] = {"verdict": "NOT_REACHED", "problems": [], "unknown": []}

#: Після коміту доказу HEAD зсувається. Ці двоє лишають дерево чистим, тож замикають цикл.
CLOSURE: tuple[str, ...] = ("operational-gate", "lane-report")


def make_command(target: str, executable: str) -> list[str]:
    return ["make", target, f"PY={executable}"]


@contextmanager
def interpreter_for_make() -> Any:
    executable = Path(sys.executable)
    if not any(char.isspace() for char in str(executable)):
        yield str(executable)
        return
    with tempfile.TemporaryDirectory(prefix="korpus-venv-") as directory:
        alias = Path(directory) / "venv"
        alias.symlink_to(Path(sys.prefix), target_is_directory=True)
        yield str(alias / "bin" / executable.name)


def run(target: str, timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        with interpreter_for_make() as executable:
            done = subprocess.run(
                make_command(target, executable),
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
    except subprocess.TimeoutExpired:
        return {"target": target, "state": "TIMED_OUT", "code": None, "seconds": timeout}
    return {
        "target": target,
        "state": "PASSED" if done.returncode == 0 else "FAILED",
        "code": done.returncode,
        "seconds": round(time.monotonic() - started, 1),
        "tail": (done.stdout + done.stderr).strip().splitlines()[-3:] if done.returncode else [],
    }


def git(*args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=str(ROOT), capture_output=True, text=True, check=False
    )
    return done.stdout.strip()


def verdict() -> dict[str, Any]:
    done = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_branch_consolidation.py"),
            "--canonical",
            "main",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return dict(json.loads(done.stdout))
    except json.JSONDecodeError:
        return {"verdict": "UNREADABLE", "problems": [done.stderr.strip()[:300]], "unknown": []}


def status(final: dict[str, Any], results: list[dict[str, Any]]) -> str:
    """PASS лише коли ВСЕ виконано і прийнято; пропуск дає INCOMPLETE, не PASS.

    Прийняття читається з ПОЛЯ `ACCEPTED`, яке виносить сам сторож зведення, а не зі
    збігу рядка `verdict`. Виміряно 03.09.2026: усі вісімнадцять кроків лану пройшли,
    а лан оголосив FAIL, бо сторож навмисно назвав свій вирок ОБСЯГОМ —
    `BRANCH_CONSOLIDATION_ACCEPTED` замість голого `ACCEPTED`, щоб його не читали як
    право на випуск. Споживач лишився на старому слові, тож лан не міг сказати PASS
    ніколи, і це була відмова про КОД, якого немає.

    Відсутнє поле — теж не прийняття: `NOT_REACHED` і `UNREADABLE` його не несуть.
    """
    if any(result["state"] not in {"PASSED", SKIPPED} for result in results):
        return "FAIL"
    if any(result["state"] == SKIPPED for result in results):
        return "INCOMPLETE"
    return "PASS" if final.get("ACCEPTED") is True else "FAIL"


def sequence(with_external: bool, timeout: float) -> tuple[list[dict[str, Any]], str | None]:
    """Кроки до першої відмови. Спинятись треба: далі числа були б про інше дерево."""
    results: list[dict[str, Any]] = []
    planned = [*STEPS, *(EXTERNAL if with_external else ())]
    for target, role in planned:
        if not with_external and target in EXTERNAL_EVIDENCE:
            results.append(
                {
                    "target": target,
                    "state": SKIPPED,
                    "code": None,
                    "seconds": 0.0,
                    "role": role,
                    "why": "доказ виробляє лише зовнішній лан; пропуск не є проходженням",
                }
            )
            continue
        outcome = run(target, timeout)
        outcome["role"] = role
        results.append(outcome)
        if outcome["state"] != "PASSED":
            return results, target
    return results, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-external", action="store_true", help="без docker-гейтів")
    parser.add_argument("--closure-only", action="store_true", help="лише замикання після коміту")
    parser.add_argument("--timeout", type=float, default=3600.0)
    parser.add_argument("--out", type=Path, default=ROOT / "var/release-verify.json")
    args = parser.parse_args()

    head = git("rev-parse", "HEAD")
    dirty = [line for line in git("status", "--porcelain").splitlines() if line]
    if dirty and not args.closure_only:
        refusal: dict[str, Any] = {
            "status": "REFUSED",
            "reason": "дерево брудне до початку — вимір на дереві, що рухається, дає числа про різні дерева",
            "dirty": dirty[:10],
            "head": head,
        }
        print(json.dumps(refusal, ensure_ascii=False, indent=2))
        return 2

    # Тотожність ПРЕДМЕТА до й після. Вимір, що змінює те, що міряє, не є виміром:
    # виміряно 02.09.2026 — усі 15 артефактів прогону лягли в `reports/`, і НУЛЬ із них
    # у обсязі джерела. Це властивість, а не випадковість, тож вона мусить перевірятись
    # щоразу, а не бути спостереженням, зробленим одного разу.
    source_before = compute_source_digest(ROOT)
    if args.closure_only:
        results = [run(target, args.timeout) for target in CLOSURE]
        stopped = next((r["target"] for r in results if r["state"] != "PASSED"), None)
    else:
        results, stopped = sequence(not args.skip_external, args.timeout)
    source_after = compute_source_digest(ROOT)
    if source_after != source_before:
        moved: dict[str, Any] = {
            "status": "INVALID",
            "reason": "джерело змінилось ПІД ЧАС виміру — числа нижче про різні дерева",
            "source_before": source_before,
            "source_after": source_after,
            "steps": results,
        }
        print(json.dumps(moved, ensure_ascii=False, indent=2))
        return 3

    final = verdict() if stopped is None else dict(NOT_REACHED)
    after = git("rev-parse", "HEAD")
    report: dict[str, Any] = {
        "schema": "korpus.release-verify.v1",
        "head_before": head,
        "head_after": after,
        "head_moved": head != after,
        "source_digest": source_before,
        "source_unmoved_during_run": True,
        "steps": results,
        "stopped_at": stopped,
        "verdict": final.get("verdict"),
        "problems": final.get("problems", []),
        "unknown": final.get("unknown", []),
        "tree_dirty_after": len(
            [line for line in git("status", "--porcelain").splitlines() if line]
        ),
        "skipped": [r["target"] for r in results if r["state"] == SKIPPED],
        "status": status(final, results),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
