#!/usr/bin/env python3
"""Записати, що конвеєр СПРАВДІ пройшов на цьому коміті, а не що міг би пройти.

Дзеркало лану (`verify_ci_mirror.py`) відповідає на структурне питання: чи виконує
конвеєр ті самі команди, що й локальний лан. Воно нічого не каже про подію. Дві
властивості носили одну назву, і замінник SI-7 кредитував реліз структурою.

Цей вимірювач питає хостований GitLab про конвеєри ДЛЯ ТОЧНОГО коміта й записує:
який конвеєр, з яким станом, які джоби завершені успішно. Обов'язковий перелік
береться з `RELEASE_ENVELOPE.json` — копія переліку тут розійшлася б із замороженим
знаменником мовчки.

Відсутність конвеєра — НЕ відмова інструмента: це стан «не вимірювалось», і звіт
каже саме це. Хибне «FAIL» про непроведений вимір коштує дорожче, ніж чесне
NOT_MEASURED: перше шукають у коді, якого немає.

    record_ci_run.py [--commit SHA] [--out ФАЙЛ] [--selftest]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENVELOPE = ROOT / "RELEASE_ENVELOPE.json"
SCHEMA = "korpus.ci-run.v1"
SUCCESS = "success"


def candidate_ci() -> dict[str, Any]:
    payload = json.loads(ENVELOPE.read_text(encoding="utf-8"))
    block = payload.get("release_candidate", {})
    ci = block.get("ci") if isinstance(block, dict) else None
    return ci if isinstance(ci, dict) else {}


def head() -> str:
    done = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return done.stdout.strip()


def glab(project: str, path: str) -> Any | None:
    """Відповідь API або None. None означає «не спитали», не «немає»."""
    done = subprocess.run(
        ["glab", "api", f"projects/{project.replace('/', '%2F')}/{path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if done.returncode != 0:
        return None
    try:
        return json.loads(done.stdout)
    except json.JSONDecodeError:
        return None


def adjudicate(
    commit: str,
    required: list[str],
    pipelines: Any,
    jobs: Any,
    *,
    pipeline_url: str = "",
) -> dict[str, Any]:
    """Вирок про прогін. Порожній перелік обов'язкових джобів — не PASS.

    `all([])` істинне, тож без цієї умови конвеєр без вимог проходив би завжди.
    """
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "commit": commit,
        "required_jobs": sorted(required),
        "completed_jobs": [],
        "failed_jobs": [],
        "pipeline": pipeline_url,
        "ran_at": datetime.now(UTC).isoformat(),
    }
    if not isinstance(pipelines, list) or not pipelines:
        report["status"] = "NOT_MEASURED"
        report["detail"] = "для цього коміта конвеєр не знайдено"
        return report
    if not required:
        report["status"] = "NOT_MEASURED"
        report["detail"] = "конверт не називає обов'язкових джобів"
        return report
    passed = sorted(
        {str(job.get("name")) for job in jobs or [] if str(job.get("status")) == SUCCESS}
    )
    failed = sorted(
        {
            str(job.get("name"))
            for job in jobs or []
            if str(job.get("status")) not in {SUCCESS, "manual", "skipped", "created"}
        }
    )
    report["completed_jobs"] = passed
    report["failed_jobs"] = failed
    missing = sorted(set(required) - set(passed))
    report["missing_jobs"] = missing
    report["status"] = "PASS" if not missing and not failed else "FAIL"
    if missing:
        report["detail"] = f"обов'язкові джоби без успіху: {missing}"
    elif failed:
        report["detail"] = f"джоби впали: {failed}"
    else:
        report["detail"] = "усі обов'язкові джоби успішні на цьому коміті"
    return report


def selftest() -> int:
    required = ["a", "b"]
    cases: list[tuple[str, Any, Any]] = [
        (
            "конвеєра для коміта немає — NOT_MEASURED, не FAIL",
            adjudicate("c" * 40, required, [], [])["status"],
            "NOT_MEASURED",
        ),
        (
            "порожній перелік вимог не проходить (all([]) істинне)",
            adjudicate("c" * 40, [], [{"id": 1}], [{"name": "a", "status": SUCCESS}])["status"],
            "NOT_MEASURED",
        ),
        (
            "усі обов'язкові успішні — PASS",
            adjudicate(
                "c" * 40,
                required,
                [{"id": 1}],
                [{"name": "a", "status": SUCCESS}, {"name": "b", "status": SUCCESS}],
            )["status"],
            "PASS",
        ),
        (
            "один обов'язковий не запустився — FAIL",
            adjudicate("c" * 40, required, [{"id": 1}], [{"name": "a", "status": SUCCESS}])[
                "status"
            ],
            "FAIL",
        ),
        (
            "необов'язковий джоб упав — теж FAIL",
            adjudicate(
                "c" * 40,
                required,
                [{"id": 1}],
                [
                    {"name": "a", "status": SUCCESS},
                    {"name": "b", "status": SUCCESS},
                    {"name": "z", "status": "failed"},
                ],
            )["status"],
            "FAIL",
        ),
        (
            "ручний джоб не рахується падінням",
            adjudicate(
                "c" * 40,
                required,
                [{"id": 1}],
                [
                    {"name": "a", "status": SUCCESS},
                    {"name": "b", "status": SUCCESS},
                    {"name": "z", "status": "manual"},
                ],
            )["status"],
            "PASS",
        ),
    ]
    passed = 0
    for name, got, want in cases:
        ok = got == want
        passed += ok
        print(f"  {'ok' if ok else 'ПРОВАЛ'} {name}: {got!r}")
    print(f"негативний контроль: {passed}/{len(cases)}")
    return 0 if passed == len(cases) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="")
    parser.add_argument("--out", type=Path, default=ROOT / "var/ci-run.json")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument(
        "--evidence-only",
        action="store_true",
        help=(
            "нуль, якщо доказ ЗАПИСАНО: вирок про прогін виносить замінник SI-7 над "
            "артефактом. Без цього лан спинявся б там, де вимір чесно каже "
            "NOT_MEASURED, а `-` перед рецептом ховав би й справжній збій."
        ),
    )
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()

    ci = candidate_ci()
    commit = arguments.commit or head()
    project = str(ci.get("project") or "")
    required = [str(name) for name in ci.get("required_jobs") or []]
    pipelines = glab(project, f"pipelines?sha={commit}") if project else None
    jobs: Any = None
    url = ""
    if isinstance(pipelines, list) and pipelines:
        newest = pipelines[0]
        url = str(newest.get("web_url") or newest.get("id") or "")
        jobs = glab(project, f"pipelines/{newest.get('id')}/jobs?per_page=100")
    report = adjudicate(commit, required, pipelines, jobs, pipeline_url=url)
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    arguments.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if arguments.evidence_only:
        return 0
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
