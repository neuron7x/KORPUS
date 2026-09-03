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
import os
import sqlite3
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
    # Записаний вхід, якого ніхто не звіряє, гірший за відсутній: він створює враження
    # прив'язки. Голова журналу — вхід звіту про журнал, і живий сервер рухає її на
    # кожну відповідь; без цієї перевірки звіт про атрибуцію лишався б «свіжим» після
    # сотні нових подій.
    head = recorded.get("audit_head")
    if head is not None:
        moved = journal_moved_under_report(database, str(head), payload)
        if moved is not None:
            return moved
    return None


def journal_moved_under_report(database: Path, head: str, payload: dict[str, Any]) -> str | None:
    """Чи журнал ЗМІНИВСЯ під звітом — на відміну від «просто виріс».

    Раніше тут стояла рівність голів, і будь-яка нова подія робила звіт несвіжим. Для
    дайджеста корпусу це правильно: інший вміст — інший предмет. Для журналу аудиту —
    ні. Журнал ДОПИСУВАНИЙ: нова подія не змінює жодного байта тих, що вже є.

    ## Межа цієї перевірки названа, бо вона вужча, ніж здається

    `event_hash` — це HMAC із ключем аудиту. Отже ПЕРЕРАХУВАТИ ланцюг без матеріалу
    ключа неможливо, а ключів у цього гейта немає й бути не мусить. Перша редакція
    правки шукала рядок із `event_hash = записана голова` й називала це «префікс цілий».
    Це було твердження, якого перевірка зробити не могла: побудовано атаку, у якій
    `payload_json` давньої події змінено, а її `event_hash` лишено старим — і перевірка
    сказала «свіжо».

    Тому тут перевіряється те, що перевіряється БЕЗ ключів:

      * якір на місці — подія із записаною головою існує;
      * ЗЧЕПЛЕННЯ префікса ціле — `previous_hash` кожної події дорівнює `event_hash`
        попередньої, а послідовність без розривів. Це ловить вставку, видалення й
        переставляння, тобто найгрубші форми підробки;
      * хвіст названий тим, чим він є: подіями, підпис яких ТУТ НЕ ПЕРЕВІРЯВСЯ.

    Чого воно НЕ доводить: що байти префікса не змінені. Зміна `payload_json` зі
    збереженням старого `event_hash` розривом зчеплення не є і тут не видна. Це
    доводить лише `measure_audit_integrity`, у якого є ключі, і саме тому релізний
    рівень (`--require-full-journal-coverage`) вимагає СВІЖОГО виміру, а не цього.

    Членство `audit_key_id` у наборі ключів звіту — не підпис. Ярлик не входить у
    канонічну форму, тож його можна переписати, не чіпаючи хешів. Тому хвіст під
    відомим ярликом дає `unverified_tail_events`, а не «атрибутований».
    """
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        live = connection.execute("select sequence, head_hash from audit_heads").fetchone()
        if live is None:
            return "у журналі немає голови"
        if str(live[1]) == head:
            return None
        anchor = connection.execute(
            "select sequence from audit_events where event_hash = ?", (head,)
        ).fetchone()
        if anchor is None:
            return "журнал переписано: події з головою цього звіту в ньому немає"
        broken = _prefix_linkage_break(connection, int(anchor[0]))
        if broken is not None:
            return f"зчеплення префікса розірване на послідовності {broken}"
        tail = connection.execute(
            "select distinct audit_key_id from audit_events where sequence > ?", (anchor[0],)
        ).fetchall()
        payload["uncovered_events"] = int(live[0]) - int(anchor[0])
        payload["prefix_integrity"] = "LINKAGE_ONLY_NO_KEYS_HERE"
    finally:
        connection.close()
    known = set(payload.get("keys_offered") or ())
    unknown = sorted({str(row[0]) for row in tail} - known)
    if unknown:
        return f"після звіту з'явились події під ключами, яких він не знав: {unknown}"
    payload["unverified_tail_events"] = payload["uncovered_events"]
    return None


def _prefix_linkage_break(connection: sqlite3.Connection, upto: int) -> int | None:
    """Перша послідовність, де зчеплення префікса рветься, або None.

    Без ключів це найсильніше, що можна стверджувати про префікс: кожна подія мусить
    називати попередню, і номери мусять іти без пропусків. Ловить вставку, видалення й
    переставляння. НЕ ловить зміну вмісту зі збереженням старого `event_hash`.
    """
    previous = "0" * 64
    expected = 1
    for sequence, prior, current in connection.execute(
        "select sequence, previous_hash, event_hash from audit_events "
        "where sequence <= ? order by sequence",
        (upto,),
    ):
        if int(sequence) != expected or str(prior) != previous:
            return int(sequence)
        previous = str(current)
        expected += 1
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
    result = {
        "axis": name,
        "state": "MEASURED",
        "value": round(value, 4),
        "floor": float(spec["floor"]),
        "population": population,
        "below_floor": value < float(spec["floor"]),
    }
    # Скільки подій дописано ПІСЛЯ виміряного відтинку. Нуль означає, що число описує
    # весь журнал; більше нуля — що воно описує префікс, і релізний рівень має право
    # цього не приймати. Без цього поля «звіт про 9831 подію» і «звіт про 9831 із 9871»
    # виглядали б однаково.
    uncovered = payload.get("uncovered_events")
    if uncovered is not None:
        result["uncovered_events"] = int(uncovered)
    return result


def failure_precedes_unknown(problems: list[str]) -> str:
    return "FAIL" if problems else "UNKNOWN"


def compose(axes: list[dict[str, Any]], relaxed: list[dict[str, Any]]) -> dict[str, Any]:
    problems: list[str] = []
    for entry in relaxed:
        if len(str(entry.get("reason", "")).strip()) < MIN_REASON:
            problems.append(f"послаблення {entry.get('axis')!r} без записаної причини")
    unmeasured = [item for item in axes if item["state"] != "MEASURED"]
    measured = [item for item in axes if item["state"] == "MEASURED"]
    below_floor = [item for item in measured if item["below_floor"]]
    for item in below_floor:
        problems.append(f"{item['axis']}: {item['value']:.4f} нижче підлоги {item['floor']:.2f}")
    if unmeasured:
        known_weakest = min(below_floor, key=lambda item: item["value"], default=None)
        return {
            "verdict": failure_precedes_unknown(problems),
            "weakest": known_weakest,
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
        ("відомий FAIL сильніший за сліпу вісь", [axis("a", 0.1, 0.8), blind], [], "FAIL"),
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
    failures.extend(_journal_selftest())
    print(
        json.dumps(
            {"selftest": len(cases) + 1 + _JOURNAL_CASES, "failed": failures},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if failures else 0


#: Скільки тверджень перевіряє `_journal_selftest`. Названо числом, бо підсумок
#: самоперевірки, який не рахує власних випадків, звітує про менше, ніж перевіряє.
_JOURNAL_CASES = 10


_ZERO = "0" * 64

#: (назва, рядки, голова, голова звіту, очікуване: None або підрядок причини)
_JOURNAL_POISONS: list[
    tuple[str, list[tuple[int, str, str, str]], tuple[int, str], str, str | None]
] = [
    ("журнал не рухався", [(1, "h1", "k1", _ZERO)], (1, "h1"), "h1", None),
    (
        "дописано під ВІДОМИМ ключем",
        [(1, "h1", "k1", _ZERO), (2, "h2", "k1", "h1")],
        (2, "h2"),
        "h1",
        None,
    ),
    (
        "подія під НЕВІДОМИМ ключем — ратчет",
        [(1, "h1", "k1", _ZERO), (2, "h2", "ПЛЕЙСХОЛДЕР", "h1")],
        (2, "h2"),
        "h1",
        "не знав",
    ),
    (
        "голову звіту переписано",
        [(1, "інший", "k1", _ZERO), (2, "h2", "k1", "інший")],
        (2, "h2"),
        "h1",
        "переписано",
    ),
    (
        "подію префікса ВИДАЛЕНО",
        [(2, "h2", "k1", "h1"), (3, "h3", "k1", "h2")],
        (3, "h3"),
        "h2",
        "зчеплення",
    ),
    (
        "зчеплення префікса РОЗІРВАНЕ",
        [(1, "h1", "k1", _ZERO), (2, "h2", "k1", "ЧУЖИЙ"), (3, "h3", "k1", "h2")],
        (3, "h3"),
        "h2",
        "зчеплення",
    ),
    (
        "події префікса ПЕРЕСТАВЛЕНІ",
        [(1, "h1", "k1", _ZERO), (3, "h3", "k1", "h1"), (2, "h2", "k1", "h3")],
        (3, "h3"),
        "h2",
        "зчеплення",
    ),
]


def _journal_selftest() -> list[str]:
    """Отрути по ДАНИХ для правила дописуваного журналу.

    Сім випадків, і шість із них доводять, що правило ЩЕ ловить: незнайомий ярлик ключа,
    переписану голову, видалення, розрив зчеплення й переставляння. Лише сьомий доводить,
    що воно перестало кричати на доброякісний ріст. Без цієї пропорції заміна рівності
    голів була б послабленням, а не виправленням.

    Форма таблична навмисно: сім написаних вручну блоків давали функцію на 79 рядків зі
    вкладеністю 4, і рецензія слушно назвала це структурним боргом у самому перевіряльнику.
    Перевіряльник, складніший за інваріант, який він охороняє, — окремий клас вади.
    """
    import tempfile

    known = {"keys_offered": ["k1"]}
    made: list[Path] = []

    def journal(rows: list[tuple[int, str, str, str]], head: tuple[int, str]) -> Path:
        """Рядок: (послідовність, event_hash, audit_key_id, previous_hash)."""
        descriptor, name = tempfile.mkstemp(suffix=".db")
        os.close(descriptor)
        path = Path(name)
        made.append(path)
        connection = sqlite3.connect(path)
        connection.execute(
            "create table audit_events "
            "(sequence int, event_hash text, audit_key_id text, previous_hash text)"
        )
        connection.execute(
            "create table audit_heads (singleton_id int, sequence int, head_hash text)"
        )
        connection.executemany("insert into audit_events values (?,?,?,?)", rows)
        connection.execute("insert into audit_heads values (1,?,?)", head)
        connection.commit()
        connection.close()
        return path

    problems: list[str] = []
    for label, rows, head, reported, want in _JOURNAL_POISONS:
        got = journal_moved_under_report(journal(rows, head), reported, dict(known))
        if want is None and got is not None:
            problems.append(f"{label}: несподівана відмова {got!r}")
        elif want is not None and (got is None or want not in got):
            problems.append(f"{label}: очікувалось {want!r}, отримано {got!r}")

    # Другий випадок несе ще три твердження: хвіст порахований, названий НЕПЕРЕВІРЕНИМ
    # і межа твердження про префікс проголошена.
    payload: dict[str, Any] = dict(known)
    journal_moved_under_report(
        journal([(1, "h1", "k1", _ZERO), (2, "h2", "k1", "h1")], (2, "h2")), "h1", payload
    )
    for key, expected in (
        ("uncovered_events", 1),
        ("unverified_tail_events", 1),
        ("prefix_integrity", "LINKAGE_ONLY_NO_KEYS_HERE"),
    ):
        if payload.get(key) != expected:
            problems.append(f"{key}: очікувалось {expected!r}, отримано {payload.get(key)!r}")

    for candidate in made:
        candidate.unlink(missing_ok=True)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--selftest", action="store_true")
    # Релізний рівень. Звичайний прогін приймає число ПРО ВИМІРЯНИЙ ВІДТИНОК: журнал
    # дописуваний, і подія, написана після виміру, не робить твердження про префікс
    # хибним. Реліз — інша справа: він стверджує про СТАН, а не про відтинок, тож
    # вимагає, щоб відтинок був цілим журналом.
    #
    # Без цього прапорця правило дописуваного журналу було б послабленням: вісь
    # перестала б ставати UNKNOWN від росту й не набула б натомість жодного місця,
    # де хвіст важить. Сигнал, який ні на що не впливає, вимірює нуль.
    parser.add_argument("--require-full-journal-coverage", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    axes = [measure_axis(name, spec, args.root) for name, spec in profile["axes"].items()]
    result = compose(axes, list(profile.get("relaxed", [])))
    uncovered = [
        (item["axis"], item["uncovered_events"])
        for item in axes
        if int(item.get("uncovered_events", 0)) > 0
    ]
    if args.require_full_journal_coverage and uncovered:
        result = {
            **result,
            "verdict": "UNKNOWN",
            "problems": [
                *result.get("problems", []),
                *(
                    f"{axis}: число описує префікс журналу, а не стан — {count} подій дописано "
                    f"після виміру; для релізу перезнімайте вимірювач безпосередньо перед віссю"
                    for axis, count in uncovered
                ),
            ],
        }
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
