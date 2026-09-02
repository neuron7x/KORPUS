#!/usr/bin/env python3
"""Що лан ВИМІРЯВ, а що просто не встиг — бо це різні речі, а код виходу їх не розрізняє.

`make` спиняється на першій відмові. Виміряно 01.09.2026: `validate` має 29 передумов і
падає на ТРЕТІЙ, тож 26 не виконуються взагалі. Повідомлення називає одну проблему, і
жодне поле не каже, у якому стані решта. «Зелено, крім однієї» і «одна червона, про 26
не відомо нічого» виглядають однаково, а це протилежні твердження.

Це `unknown-is-not-pass` на рівні лану: порядок рядків у Makefile став мовчазним
регулятором того, що взагалі міряється. Ціль, поставлена першою, боронить; та сама ціль,
поставлена після червоної, не боронить нічого й виглядає так само.

## Чому не `make -k`

Він дає ДВА стани — пройшло і впало — і не має третього. Ціль, до якої не дійшли, у
ньому не відрізняється від відсутньої, а сам код виходу не несе, скільки їх було. Тут
третій стан є первинним: перелік цілей будується ДО прогону і заповнюється `NOT_RUN`, тож
обвал самого бігуна лишає невиконані видимими, а не пропущеними.

## Перелік береться з Makefile, не з конфіга

Копія переліку — це друге оголошення того самого факту, і воно розійдеться мовчки саме
тоді, коли хтось додасть ціль. Тому передумови читаються з правила `<лан>:` у Makefile,
і тест доводить, що зміна в Makefile видима бігунові.

## Таймаут — не проходження

Ціль, що не вклалась, не «пройшла» й не «впала»: вона не дала вироку. Власний стан,
власний рядок у звіті, і вирок такий самий негативний, як відмова — інакше найдорожча
перевірка стає найтихішою.

    run_lane.py --lane validate
    run_lane.py --selftest
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

from korpus.application.provenance import compute_source_digest  # noqa: E402

MAKEFILE = ROOT / "Makefile"

PASSED, FAILED, TIMED_OUT, NOT_RUN = "PASSED", "FAILED", "TIMED_OUT", "NOT_RUN"


def tree_identity(root: Path = ROOT) -> dict[str, str]:
    """Тотожність дерева, про яке буде звіт: коміт І вміст.

    Двоє, бо ловлять різне. Коміт каже, ЯКА ревізія; дайджест ловить брудне дерево, де
    коміт той самий, а файли інші. Читач звіту не має способу дізнатись жодне з двох, якщо
    їх туди не покласти, — і саме тому попередня прив'язка була годинником.
    """
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return {
        "source_commit": head.stdout.strip() if head.returncode == 0 else "",
        "source_digest": compute_source_digest(root),
    }


def lane_targets(makefile: Path, lane: str) -> list[str]:
    """Передумови правила `<лан>:` — з дерева, не з копії переліку.

    Береться ПЕРШЕ правило з таким іменем: `make` при двох рецептах лишає останній і
    попереджає, але передумови для нас однакові, а мовчазне злиття двох правил
    приховало б, що ціль оголошена двічі.
    """
    text = makefile.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(lane)}:([^=\n]*)$", re.MULTILINE)
    found = pattern.search(text)
    if found is None:
        raise SystemExit(f"у Makefile немає правила {lane}:")
    targets = [item for item in found.group(1).split() if not item.startswith(("$", "#"))]
    # РЕБРА З РЕЦЕПТА. Лан може складатися не з передумов, а з викликів `$(MAKE) ціль`,
    # і саме так зроблені `check-nightly`, `corpus-axes` та `nightly-evidence`.
    #
    # ВИМІРЯНО 02.09.2026: для всіх трьох ця функція повертала НУЛЬ цілей. Тобто
    # інструмент, чиє єдине призначення — показати третій стан `NOT_RUN`, був сліпий
    # саме до лану, що несе всі 16 осей відповіді. Порожній перелік читався б як
    # «лан порожній», а не як «я його не бачу».
    #
    # `verify_gate_closure.parse_graph` читає ці ребра з 31.08 і має на них негативний
    # контроль. Закон був записаний в одному інструменті й не поширився на сусідній —
    # один раз записаний закон сам не поширюється.
    body = text[found.end() :]
    recipe = body[: body.find("\n\n")] if "\n\n" in body else body
    for name in re.findall(r"^\t\s*\$\(MAKE\)\s+([A-Za-z][\w.-]*)", recipe, re.MULTILINE):
        if name not in targets:
            targets.append(name)
    return targets


def run_target(target: str, timeout: float, make: str = "make") -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [make, target],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"state": TIMED_OUT, "code": None, "seconds": round(time.monotonic() - started, 1)}
    tail = (completed.stdout + completed.stderr).strip().splitlines()
    return {
        "state": PASSED if completed.returncode == 0 else FAILED,
        "code": completed.returncode,
        "seconds": round(time.monotonic() - started, 1),
        "tail": tail[-3:] if completed.returncode else [],
    }


def summarise(results: dict[str, dict[str, Any]], lane: str) -> dict[str, Any]:
    counts = {state: 0 for state in (PASSED, FAILED, TIMED_OUT, NOT_RUN)}
    for item in results.values():
        counts[item["state"]] += 1
    return {
        "schema": "korpus.lane-report.v1",
        "lane": lane,
        "targets": len(results),
        "passed": counts[PASSED],
        "failed": counts[FAILED],
        "timed_out": counts[TIMED_OUT],
        # Первинне число цього звіту. Нуль тут — єдине, що робить решту твердженнями
        # про лан, а не про його початок.
        "not_run": counts[NOT_RUN],
        "failed_targets": [name for name, item in results.items() if item["state"] == FAILED],
        "timed_out_targets": [name for name, item in results.items() if item["state"] == TIMED_OUT],
        "not_run_targets": [name for name, item in results.items() if item["state"] == NOT_RUN],
        "status": "MEASURED" if counts[NOT_RUN] == 0 else "PARTIAL",
        "detail": results,
    }


def execute(
    lane: str,
    timeout: float,
    out: Path,
    make: str = "make",
    makefile: Path | None = None,
) -> dict[str, Any]:
    targets = lane_targets(makefile or MAKEFILE, lane)
    if not targets:
        raise SystemExit(f"лан {lane} не має передумов — це відмова, а не результат")
    # Тотожність дерева знімається ДО першої цілі: звіт має сказати, ЩО він міряв, а не
    # лише коли. Прив'язка часом («звіт старший за коміт») пропускає прогін, що почався
    # до коміту й скінчився після нього, і нічого не каже про вміст. Виміряно 02.09.2026:
    # рівно на цьому вирок читав лан, знятий на іншому дереві, і називав це UNKNOWN.
    identity = tree_identity()
    # Заповнюється ДО прогону. Обвал бігуна тоді лишає невиконані видимими; перелік,
    # що дописується по ходу, зробив би їх невідрізненними від неоголошених.
    results: dict[str, dict[str, Any]] = {
        name: {"state": NOT_RUN, "code": None, "seconds": 0.0} for name in targets
    }
    for name in targets:
        results[name] = run_target(name, timeout, make)
        report = summarise(results, lane)
        report["ran_at"] = datetime.now(UTC).isoformat()
        report.update(identity)
        # Цілі лану самі пишуть у дерево (маніфести, звіти), тож рух вмісту під час
        # прогону — норма. Ненормальний рух ДЖЕРЕЛА: тоді половина лану про одне дерево,
        # половина про інше, і жодна половина не названа.
        report["source_moved_during_run"] = (
            tree_identity()["source_commit"] != (identity["source_commit"])
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def selftest() -> int:
    """Негативні контролі: бігун, який не вміє сказати «не запускалось», не є бігуном."""
    checks: list[tuple[str, Any, Any]] = []
    every: dict[str, dict[str, Any]] = {
        "a": {"state": PASSED, "code": 0, "seconds": 0.1},
        "b": {"state": PASSED, "code": 0, "seconds": 0.1},
    }
    checks.append(("усе пройшло — MEASURED", summarise(every, "l")["status"], "MEASURED"))
    stopped: dict[str, dict[str, Any]] = {
        "a": {"state": FAILED, "code": 1, "seconds": 0.1},
        "b": {"state": NOT_RUN, "code": None, "seconds": 0.0},
    }
    verdict = summarise(stopped, "l")
    checks.append(("невиконане названо", verdict["not_run_targets"], ["b"]))
    checks.append(("невиконане робить лан PARTIAL", verdict["status"], "PARTIAL"))
    checks.append(("невиконане НЕ рахується пройденим", verdict["passed"], 0))
    timed: dict[str, dict[str, Any]] = {"a": {"state": TIMED_OUT, "code": None, "seconds": 9.0}}
    checks.append(("таймаут не є проходженням", summarise(timed, "l")["passed"], 0))
    checks.append(("таймаут названо окремо", summarise(timed, "l")["timed_out_targets"], ["a"]))

    makefile = ROOT / "Makefile"
    targets = lane_targets(makefile, "validate")
    checks.append(("передумови читаються з Makefile", len(targets) > 5, True))
    checks.append(("перелік не містить змінних", [t for t in targets if "$" in t], []))

    passed = 0
    for name, got, want in checks:
        ok = got == want
        passed += ok
        print(f"  {'ok' if ok else 'ПРОВАЛ'} {name}: {got!r}")
    print(f"негативний контроль: {passed}/{len(checks)}")
    return 0 if passed == len(checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", default="validate")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--selftest", action="store_true")
    arguments = parser.parse_args()
    if arguments.selftest:
        return selftest()
    out = arguments.out or ROOT / f"var/lane-{arguments.lane}.json"
    report = execute(arguments.lane, arguments.timeout, out)
    print(
        json.dumps({k: v for k, v in report.items() if k != "detail"}, ensure_ascii=False, indent=2)
    )
    return 0 if report["failed"] == report["timed_out"] == report["not_run"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
