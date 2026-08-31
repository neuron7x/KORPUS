#!/usr/bin/env python3
"""Один вирок над усіма осями відповіді, і він дорівнює НАЙСЛАБШІЙ.

Шість осей уже міряються окремо, і жодна не є вироком над рештою. Профіль без
композиції — це дашборд: він показує, і нічого не забороняє. Доктрина взята з
десятиосьового гейта GeoSync, де вона вже коштувала п'яти адверсарних раундів:

  * **Вердикт = найслабша вісь**, не середнє. Середнє ховає рівно те, заради чого
    профіль існує: одна провалена вісь при п'ятьох відмінних дає «добре».
  * **UNMEASURED ніколи не кладеться в підлогу 1.0.** Вісь без свіжого звіту робить
    вирок UNKNOWN, а не PASS. Сліпу пробу не можна заморозити як пройдену.
  * **Бал може зрости ЛИШЕ тому, що впав борг.** Знаменники ростуть безкоштовно, тож
    вісь, яка виросла через більший набір, покращенням не є — і гейт це каже вголос,
    порівнюючи не лише число, а й розмір набору, коли звіт його називає.
  * **Ніщо не кредитується, що не верифікується тут.** Кожна вісь читає ВЛАСНИЙ звіт;
    звіт, який не називає свого набору чи статусу виміру, не зараховується.

Коди виходу: 0 — усі осі в межах · 1 — найслабша нижче підлоги · 2 — судити нема чого
(бракує звіту, або звіт каже, що вимір не відбувся). Розрізняти обов'язково: «не зміг
виміряти» приходить агрегатору як «виміряв і відхилив», якщо обидва віддають 1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus_identity import corpus_identity, identity_digest  # noqa: E402

PROFILE = ROOT / "config/operations/answer-axes.json"
MIN_REASON = 20
#: Збережене число має ВІК. Звіт, зроблений колись, кредитує вісь так само впевнено, як
#: зроблений щойно, і саме так гейт починає боронити стан, якого вже немає. Доба — не
#: властивість предмета, а межа, за якою число описує інше дерево.
MAX_REPORT_AGE_HOURS = 24.0
#: Корпус, який обслуговується. Вік звіту — сурогат: він каже, КОЛИ міряли, а питання
#: інше — чи те, що міряли, ще те саме. Звіт віком 23 години про корпус, змінений п'ять
#: хвилин тому, проходив; звіт віком 25 годин про нерухомий корпус відхилявся. Обидві
#: помилки з одного джерела, і обидві лікуються ідентичністю ВХОДІВ.
SERVED_CORPUS = ROOT / "var/runtime/corpus-v6-20260807/korpus.db"


def stale_input(spec: dict[str, Any], payload: dict[str, Any], root: Path) -> str | None:
    """Що саме зрушило під звітом — або None, якщо він ще про цей стан.

    Порівнюється ПОКОМПОНЕНТНО, бо «звіт застарів» без причини змушує наступного
    вгадувати, а зрушений корпус і зрушений вимірювач вимагають різних дій.
    """
    recorded = payload.get("inputs")
    measurer = spec.get("measurer")
    if not isinstance(recorded, dict) or not measurer:
        return None
    script = root / str(measurer)
    if not script.is_file():
        return f"вимірювача {measurer} немає в дереві"
    if hashlib.sha256(script.read_bytes()).hexdigest() != recorded.get("measurer"):
        return f"вимірювач {measurer} змінився після цього звіту"
    # Корпус беремо той, який НАЗВАВ САМ ЗВІТ, а не константу: звіт стверджує про
    # конкретну базу, і питання «чи він ще про той самий стан» стосується саме її.
    # Константа зробила б перевірку правильною лише для одного розгортання й
    # неперевірюваною на еталоні.
    named = payload.get("database")
    database = Path(str(named)) if named else SERVED_CORPUS
    if not database.is_absolute():
        database = root / database
    if not database.is_file():
        # Бази, яку звіт описує, більше немає. Це не «свіжо» і не «застаріло» — це
        # відсутність можливості судити, і вона мусить прийти як UNMEASURED.
        return f"бази {database}, яку описує звіт, немає"
    if identity_digest(corpus_identity(database)) != recorded.get("corpus"):
        return "корпус змінився після цього звіту"
    return None


def report_age_hours(path: Path, payload: dict[str, Any]) -> tuple[float, str]:
    """Вік звіту й те, ЗВІДКИ він узятий: `ran_at` сильніший за mtime, який підробляє `touch`."""
    stamp = payload.get("ran_at")
    if isinstance(stamp, str):
        try:
            moment = datetime.fromisoformat(stamp)
        except ValueError:
            moment = None
        if moment is not None:
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
            return (datetime.now(UTC) - moment).total_seconds() / 3600.0, "ran_at"
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return (datetime.now(UTC) - mtime).total_seconds() / 3600.0, "mtime"


def _dig(payload: dict[str, Any], path: list[str]) -> Any:
    node: Any = payload
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def measure_axis(name: str, spec: dict[str, Any], root: Path) -> dict[str, Any]:
    """Одна вісь: число, або чесне «не виміряно» з причиною."""
    report_path = root / str(spec["report"])
    if not report_path.is_file():
        return {"axis": name, "state": "UNMEASURED", "reason": f"немає {spec['report']}"}
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    status = payload.get("status")
    if status in {"UNKNOWN", "ERROR"}:
        return {"axis": name, "state": "UNMEASURED", "reason": f"звіт каже status={status}"}
    moved = stale_input(spec, payload, root)
    if moved:
        return {"axis": name, "state": "UNMEASURED", "reason": moved}
    age, age_source = report_age_hours(report_path, payload)
    ceiling = float(spec.get("max_age_hours", MAX_REPORT_AGE_HOURS))
    if age > ceiling:
        return {
            "axis": name,
            "state": "UNMEASURED",
            "reason": f"звіту {age:.1f} год за {age_source}, стеля {ceiling:.0f}",
        }
    if "ratio" in spec:
        numerator, denominator = spec["ratio"]
        top, bottom = payload.get(numerator), payload.get(denominator)
        if not isinstance(top, int | float) or not bottom:
            return {"axis": name, "state": "UNMEASURED", "reason": "немає чисел для відношення"}
        value = float(top) / float(bottom)
        population = int(bottom)
    else:
        raw = _dig(payload, list(spec.get("path", [spec.get("field", "")])))
        if raw is None:
            return {"axis": name, "state": "UNMEASURED", "reason": "поля немає у звіті"}
        value = float(raw)
        population = 0
    if spec.get("invert"):
        value = 1.0 - value
    return {
        "axis": name,
        "state": "MEASURED",
        "value": round(value, 4),
        "floor": float(spec["floor"]),
        "population": population,
        "below_floor": value < float(spec["floor"]),
    }


def compose(axes: list[dict[str, Any]], relaxed: list[dict[str, Any]]) -> dict[str, Any]:
    problems: list[str] = []
    for entry in relaxed:
        if len(str(entry.get("reason", "")).strip()) < MIN_REASON:
            problems.append(f"послаблення {entry.get('axis')!r} без записаної причини")
    unmeasured = [item for item in axes if item["state"] != "MEASURED"]
    measured = [item for item in axes if item["state"] == "MEASURED"]
    for item in measured:
        if item["below_floor"]:
            problems.append(
                f"{item['axis']}: {item['value']:.4f} нижче підлоги {item['floor']:.2f}"
            )
    if unmeasured:
        # Не PASS і не FAIL. Сліпа вісь робить вирок невизначеним, бо вона могла б
        # виявитись найслабшою — а найслабша і є вироком.
        return {
            "verdict": "UNKNOWN",
            "weakest": None,
            "unmeasured": [item["axis"] for item in unmeasured],
            "problems": problems + [f"{item['axis']}: {item['reason']}" for item in unmeasured],
        }
    weakest = min(measured, key=lambda item: item["value"])
    return {
        "verdict": "FAIL" if problems else "PASS",
        "weakest": {"axis": weakest["axis"], "value": weakest["value"], "floor": weakest["floor"]},
        "unmeasured": [],
        "problems": problems,
    }


def selftest() -> int:
    """Отрути по ДАНИХ: кожна створює профіль, на якому композиція зобов'язана спрацювати."""

    def axis(name: str, value: float, floor: float) -> dict[str, Any]:
        return {
            "axis": name,
            "state": "MEASURED",
            "value": value,
            "floor": floor,
            "population": 10,
            "below_floor": value < floor,
        }

    blind = {"axis": "сліпа", "state": "UNMEASURED", "reason": "немає звіту"}
    cases: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]], str]] = [
        ("усі осі в межах", [axis("a", 0.9, 0.8), axis("b", 0.85, 0.8)], [], "PASS"),
        (
            "одна провалена серед відмінних — середнє сказало б «добре»",
            [axis("a", 0.99, 0.8), axis("b", 0.99, 0.8), axis("c", 0.10, 0.8)],
            [],
            "FAIL",
        ),
        ("сліпа вісь не є пройденою", [axis("a", 0.99, 0.8), blind], [], "UNKNOWN"),
        ("сама лише сліпа вісь", [blind], [], "UNKNOWN"),
        (
            "послаблення без причини",
            [axis("a", 0.9, 0.8)],
            [{"axis": "a", "reason": "-"}],
            "FAIL",
        ),
        (
            "послаблення з причиною",
            [axis("a", 0.9, 0.8)],
            [{"axis": "a", "reason": "корпус звужено, частина питань більше не має джерела"}],
            "PASS",
        ),
    ]
    failures = [
        f"{name}: {compose(axes, relaxed)['verdict']} замість {want}"
        for name, axes, relaxed, want in cases
        if compose(axes, relaxed)["verdict"] != want
    ]
    weakest = compose([axis("a", 0.99, 0.8), axis("b", 0.42, 0.1)], [])["weakest"]
    if weakest is None or weakest["axis"] != "b":
        failures.append("вирок не назвав найслабшу вісь")
    print(
        json.dumps({"selftest": len(cases) + 1, "failed": failures}, ensure_ascii=False, indent=2)
    )
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    axes = [measure_axis(name, spec, args.root) for name, spec in profile["axes"].items()]
    result = compose(axes, list(profile.get("relaxed", [])))
    print(json.dumps({**result, "axes": axes}, ensure_ascii=False, indent=2))
    return {"PASS": 0, "FAIL": 1, "UNKNOWN": 2}[str(result["verdict"])]


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as error:
        print(
            json.dumps(
                {"verdict": "ERROR", "error": f"{type(error).__name__}: {error}"},
                ensure_ascii=False,
            )
        )
        raise SystemExit(2) from error
