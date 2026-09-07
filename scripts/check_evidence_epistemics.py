#!/usr/bin/env python3
"""Чи кожен артефакт доказу знає, ПРО ЩО він, ЗА ЯКИХ УМОВ, і хто його читає.

За дві доби кампанії 05–07.09.2026 знайдено близько сорока вад, і кожна виглядала
окремою. Вони не окремі. Це ПʼЯТЬ РОДІВ, і головне про них — не те, що їх пʼять, а те,
що **кожен виявляється лише своїм експериментом**. Жоден із чотирьох інших його не бачить.

    1. ПРЕДМЕТ      артефакт називає, про яке дерево він, і це дерево — поточне.
                    Без осі: репродукція з чистої кімнати два тижні свідчила про АРХІВ
                    (GitHub, «нічого не стверджує»), а не про основу, яку судить конвеєр.
                    Проби навантаження міряли пілот на PostgreSQL, тоді як 256 документів
                    корпусу живуть за іншою службою. Числа були правдиві — про інший предмет.

    2. УМОВА        артефакт називає стан світу, за якого число дійсне.
                    Без осі: «холодний старт» означав і 7 секунд від рестарту, і 131 —
                    5,569 с проти 1,5 с на ОДНІЙ ревізії. Ратчет порівнював виміри різних
                    систем і не мав як це помітити.

    3. ЗНАМЕННИК    артефакт несе розмір популяції, і він не нульовий.
                    Без осі: `all([])` істинне, `ARMED 0/0` з кодом 0, нуль перехешованих
                    обʼєктів і чиста перевірка нерозрізненні. Вирок, узятий над порожньою
                    множиною, зелений саме в тому стані, заради якого існує.

    4. ПОХОДЖЕННЯ   артефакт називає, хто і коли його зробив.
                    Без осі: 07.09 о 07:39:30 вирок `PASS` виробив скрипт, редакції якого
                    немає в жодній із дванадцяти ревізій; збігся з правильним ВИПАДКОВО.
                    Десятьма годинами раніше чужа сесія перезаписала десять артефактів —
                    теж збіглося випадково. Двічі за добу походження встановлювалось
                    перезняттям, а не самим артефактом.

    5. СПОЖИВАЧ     артефакт хтось ЧИТАЄ.
                    Без осі: `var/blank-input-baseline.json` не читає ні гейт, ні предикат,
                    ні ратчет. Доказ без споживача — документ, і саме тому вада всередині
                    нього прожила непоміченою: пробу ніхто не запускав і виходу не читав.

## Чому саме пʼять, а не один список

Осі НЕЗАЛЕЖНІ, і це твердження перевірне: для кожної осі в дереві знаходиться артефакт,
що має чотири інші й не має цієї. Якби вони були одним родом, такого артефакта не було б
для щонайменше однієї осі. Ця перевірка виконується (`--independence`) і є негативним
контролем самої таксономії: вона може показати, що вісь зайва.

## Чого цей гейт НЕ робить

Він не питає, чи вирок артефакта ПРАВИЛЬНИЙ. Він питає, чи артефакт узагалі здатен бути
неправильним у спосіб, який хтось помітить. Це різні питання, і друге дешевше.

    check_evidence_epistemics.py [--out ФАЙЛ] [--independence]
    check_evidence_epistemics.py --selftest
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/api/src"), str(ROOT / "scripts")]
from korpus.application.provenance import compute_source_digest  # noqa: E402

AXES = ("subject", "condition", "denominator", "provenance", "consumer")

#: Поля, якими артефакт називає ПРЕДМЕТ.
SUBJECT_FIELDS = ("source_tree_sha256", "source_digest", "commit", "commit_sha", "candidate_sha")
#: Поля, якими він називає УМОВУ — стан світу, за якого число дійсне.
CONDITION_FIELDS = (
    "environment_class",
    "conditions",
    "profile",
    "service_ages_seconds",
    "scale_class",
    "evidence_class",
    "context",
    "digest_scope",
    "base",
    "backend",
    "class",
)
#: Поля, якими він називає ЗНАМЕННИК. Порожня популяція — не згода.
COUNT_HINTS = (
    "total",
    "count",
    "checked",
    "tests",
    "population",
    "examined",
    "requests",
    "predicates_total",
    "measured",
    "declared",
    "answered",
    "cases",
    "gates",
    "shards",
    "spans",
    "documents",
    "files",
    "scanned",
    "objects",
    "mutants",
    "targets_declared",
)
#: Колекції СУДЖЕНИХ одиниць. Структурна міра знаменника: вирок квантифікує над
#: множиною, і розмір цієї множини є знаменником незалежно від того, як її назвали.
JUDGED_COLLECTIONS = (
    "checks",
    "states",
    "items",
    "results",
    "rows",
    "predicates",
    "gates",
    "findings",
    "scanners",
    "targets",
    "entries",
    "claims",
    "violations",
    "cases",
)
#: Поля, якими він називає ПОХОДЖЕННЯ.
ORIGIN_FIELDS = ("generated_at", "measured_at", "ran_at", "created_at", "produced_by", "schema")
#: Де шукати споживача. `var/` не шукаємо: артефакт, який читає лише інший артефакт,
#: споживачем не забезпечений.
CONSUMER_ROOTS = ("scripts", "apps/api/src", "apps/api/tests", "Makefile", ".gitlab-ci.yml")


def _load(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _flat_numbers(payload: Any, depth: int = 0) -> list[tuple[str, int]]:
    """Пари (ім'я, число) з двох верхніх рівнів. Глибше — вже не знаменник вироку."""
    found: list[tuple[str, int]] = []
    if depth > 2 or not isinstance(payload, dict):
        return found
    for key, value in payload.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            found.append((str(key), value))
        elif isinstance(value, dict):
            found.extend(_flat_numbers(value, depth + 1))
        elif isinstance(value, list) and depth < 2:
            found.append((f"{key}[]", len(value)))
    return found


def has_subject(payload: dict[str, Any]) -> bool:
    return any(str(payload.get(name) or "") for name in SUBJECT_FIELDS)


def subject_is_current(payload: dict[str, Any], digest: str) -> bool | None:
    """None — артефакт предмета не називає, тож про свіжість питати нема чого."""
    declared = str(payload.get("source_tree_sha256") or payload.get("source_digest") or "")
    if not declared:
        return None
    return declared == digest


def has_condition(payload: dict[str, Any]) -> bool:
    return any(payload.get(name) not in (None, "", {}, []) for name in CONDITION_FIELDS)


#: Імена, за якими число НЕ є лічильником популяції. Цей перелік ЗАМКНЕНИЙ — величини
#: часу, розміру, тотожності й частки вичерпні, — тоді як перелік слів для «скільки
#: одиниць» відкритий і поповнюється кожним новим автором. Тому вісь судить ВИКЛЮЧЕННЯМ.
#: Дві попередні редакції судили включенням і дали 60 % хибнопозитивів: пропустили
#: `questions_measured`, потім `python`/`web`, потім `references`/`controls`.
NOT_A_COUNTER = (
    "second",
    "ms",
    "milli",
    "micro",
    "nano",
    "byte",
    "size",
    "sha",
    "hash",
    "digest",
    "timestamp",
    "epoch",
    "port",
    "version",
    "percent",
    "rate",
    "ratio",
    "score",
    "threshold",
    "ceiling",
    "floor",
    "code",
    "id",
    "year",
    "index",
    "sequence",
)


def is_counter(name: str) -> bool:
    """Чи це число рахує ОДИНИЦІ. Судиться виключенням, бо цей бік замкнений."""
    lowered = name.lower()
    return not any(word in lowered for word in NOT_A_COUNTER)


def judged_population(payload: dict[str, Any]) -> int:
    """Розмір множини, над якою вирок квантифікує. Структурна міра, БЕЗ імен.

    Перші дві редакції судили ІМЕНА колекцій і промахувались двічі: спершу пропустили
    `questions_measured`, потім `python`/`web` у звіті локів. Перелік імен не замикається —
    їх вигадує кожен автор наново. Тому міра тут форма: колекція СУДЖЕНИХ одиниць — це
    непорожній словник або список, елементи якого самі є судимими (словники або булеві),
    а не рядки прози.
    """
    sizes = [0]
    for name, value in payload.items():
        if isinstance(value, dict | list) and value:
            sizes.append(len(value))
        elif (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value > 0
            and is_counter(name)
        ):
            sizes.append(value)
    return max(sizes)


def empty_quantifier(payload: dict[str, Any]) -> bool:
    """Вирок PASS, узятий над НУЛЬОВОЮ популяцією.

    Це не «бракує поля» — це `all([])`, істинне за побудовою. Гейт у такому стані
    зелений рівно тоді, коли міряти нема чого, тобто саме в тому стані, заради якого він
    існує. Виміряно на цьому дереві тричі за добу: `ARMED 0/0` з кодом 0, нуль
    перехешованих обʼєктів при чистій перевірці, і `anchor_gap` нуль при якорі ПОПЕРЕДУ.
    """
    verdict = str(payload.get("status") or payload.get("verdict") or "")
    if verdict.upper() not in {"PASS", "OK", "SUCCESS", "SATISFIED"}:
        return False
    return judged_population(payload) == 0


def has_denominator(payload: dict[str, Any]) -> bool:
    """Не «є число», а «вирок знає, над скількома одиницями він узятий».

    Дві незалежні міри, бо кожна окремо промахується: структурна не бачить артефакта, що
    несе лише лічильник, а лексична не бачить того, хто назвав популяцію по-своєму.
    Обидві промахи виміряні на цьому ж дереві, не уявні.
    """
    return judged_population(payload) > 0


def has_provenance(payload: dict[str, Any], depth: int = 0) -> bool:
    """Походження шукається і ВКЛАДЕНИМ.

    Перша редакція дивилась лише на верхній рівень і оголосила `var/recovery-report.json`
    безпохідним, тоді як він несе `provenance.measured_at`. Той самий клас, що й вище:
    перевірка бачила не предмет, а місце, де вона звикла його бачити.
    """
    if any(payload.get(name) for name in ORIGIN_FIELDS):
        return True
    if depth >= 2:
        return False
    return any(
        has_provenance(value, depth + 1) for value in payload.values() if isinstance(value, dict)
    )


def _grep(relative: str) -> bool:
    completed = subprocess.run(
        ["git", "grep", "-l", "--fixed-strings", relative, "--", *CONSUMER_ROOTS],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(completed.stdout.strip())


def has_consumer(relative: str) -> bool:
    """Чи ЧИТАЄ його щось у коді. Ім'я файла шукається і повним шляхом, і базовим:
    споживач може складати шлях із частин, і тоді повний рядок у дереві не зустрічається."""
    return _grep(relative) or _grep(Path(relative).name)


def judge(path: Path, payload: dict[str, Any], digest: str) -> dict[str, Any]:
    relative = path.relative_to(ROOT).as_posix()
    current = subject_is_current(payload, digest)
    axes = {
        "subject": has_subject(payload),
        "condition": has_condition(payload),
        "denominator": has_denominator(payload),
        "provenance": has_provenance(payload),
        "consumer": has_consumer(relative),
    }
    return {
        "artifact": relative,
        **axes,
        "subject_is_current": current,
        "empty_quantifier": empty_quantifier(payload),
        "judged_population": judged_population(payload),
        "missing": sorted(name for name, ok in axes.items() if not ok),
        "complete": all(axes.values()),
    }


def artifacts(root: Path) -> list[Path]:
    """Артефакти з ВИРОКОМ. Файл без вироку не є доказом і сюди не входить."""
    found: list[Path] = []
    for pattern in (
        "var/*.json",
        "var/production/*.json",
        "reports/*.json",
        "reports/closure/*.json",
    ):
        for path in sorted(root.glob(pattern)):
            payload = _load(path)
            if payload and ({"status", "checks", "verdict", "failures"} & set(payload)):
                found.append(path)
    return found


def independence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Негативний контроль САМОЇ таксономії.

    Вісь зайва, якщо в дереві немає артефакта, який має всі інші й не має її: тоді вона
    нічого не розрізняє понад сусідів. Ця перевірка може ЗНЯТИ вісь, і саме тому вона тут.
    """
    witnesses: dict[str, str | None] = {}
    for axis in AXES:
        others = [other for other in AXES if other != axis]
        witness = next(
            (row["artifact"] for row in rows if not row[axis] and all(row[o] for o in others)),
            None,
        )
        witnesses[axis] = witness
    return {
        "witnesses": witnesses,
        "axes_without_witness": sorted(a for a, w in witnesses.items() if w is None),
        "interpretation": (
            "Свідок осі — артефакт, що має чотири інші й не має цієї. Вісь без свідка не "
            "доведена як незалежна на ЦЬОМУ дереві: вона або зайва, або її предмет тут не "
            "трапляється. Це не вирок про таксономію — це межа виміру."
        ),
    }


def build(root: Path = ROOT) -> dict[str, Any]:
    digest = compute_source_digest(root)
    rows = [judge(path, _load(path) or {}, digest) for path in artifacts(root)]
    stale = [r["artifact"] for r in rows if r["subject_is_current"] is False]
    hollow = [r["artifact"] for r in rows if r["empty_quantifier"]]
    by_axis = {axis: sum(1 for r in rows if r[axis]) for axis in AXES}
    return {
        "schema": "korpus.evidence-epistemics.v1",
        "source_tree_sha256": digest,
        "artifacts_examined": len(rows),
        "complete": sum(1 for r in rows if r["complete"]),
        "by_axis": by_axis,
        "stale_subject": stale,
        "empty_quantifier_pass": hollow,
        "rows": rows,
        "interpretation": (
            "Гейт не питає, чи вирок артефакта правильний. Він питає, чи артефакт здатен "
            "бути неправильним у спосіб, який хтось помітить. Артефакт без ПРЕДМЕТА не "
            "прив'язаний ні до чого; без УМОВИ його число не порівнюване з іншим таким "
            "самим; без ЗНАМЕННИКА він зелений над порожньою множиною; без ПОХОДЖЕННЯ його "
            "неможливо відрізнити від фантомного; без СПОЖИВАЧА він документ, не доказ."
        ),
    }


def selftest() -> int:
    """Отрути по ДАНИХ: кожна вимикає рівно одну вісь, решта мусять лишитись."""
    full = {
        "status": "PASS",
        "source_tree_sha256": "a" * 64,
        "environment_class": "PRODUCTION_LIKE",
        "checks_total": 12,
        "generated_at": "2026-09-07T00:00:00+00:00",
    }
    cases: list[tuple[str, object, object]] = [
        ("повний артефакт має предмет", has_subject(full), True),
        (
            "без предмета",
            has_subject({k: v for k, v in full.items() if k != "source_tree_sha256"}),
            False,
        ),
        ("повний має умову", has_condition(full), True),
        (
            "без умови",
            has_condition({k: v for k, v in full.items() if k != "environment_class"}),
            False,
        ),
        ("повний має знаменник", has_denominator(full), True),
        ("нульова популяція не є знаменником", has_denominator({**full, "checks_total": 0}), False),
        ("число, що не є лічильником, знаменником не є", has_denominator({"seconds": 5}), False),
        ("повний має походження", has_provenance(full), True),
        (
            "без походження",
            has_provenance({k: v for k, v in full.items() if k != "generated_at"}),
            False,
        ),
        ("булеве не рахується за лічильник", has_denominator({"checks_total": True}), False),
        ("список як популяція", has_denominator({"targets_declared": [1, 2, 3]}), True),
        # Дві регресії на ВЛАСНІ хибнопозитиви першої редакції, знайдені звіркою свідків.
        ("популяція, названа по-своєму", has_denominator({"questions_measured": 20}), True),
        ("структурна популяція без лічильника", has_denominator({"checks": {"a": True}}), True),
        ("порожня колекція суджених — не популяція", has_denominator({"checks": {}}), False),
        (
            "PASS над нулем — порожній квантор",
            empty_quantifier({"status": "PASS", "checks": {}}),
            True,
        ),
        (
            "PASS над непорожнім — не порожній квантор",
            empty_quantifier({"status": "PASS", "checks": {"a": True}}),
            False,
        ),
        (
            "FAIL над нулем порожнім квантором не є",
            empty_quantifier({"status": "FAIL", "checks": {}}),
            False,
        ),
        (
            "проза не є популяцією",
            judged_population({"interpretation": "довгий текст", "note": "ще один"}),
            0,
        ),
        (
            "вкладене походження",
            has_provenance({"provenance": {"measured_at": "2026-09-07"}}),
            True,
        ),
        (
            "походження глибше двох рівнів не рахується",
            has_provenance({"a": {"b": {"c": {"measured_at": "x"}}}}),
            False,
        ),
        ("порожній список — не популяція", has_denominator({"targets_declared": []}), False),
        ("свіжість: збіг", subject_is_current({"source_tree_sha256": "b" * 64}, "b" * 64), True),
        (
            "свіжість: розбіжність",
            subject_is_current({"source_tree_sha256": "c" * 64}, "b" * 64),
            False,
        ),
        ("свіжість без предмета — не питання", subject_is_current({}, "b" * 64), None),
    ]
    bad = [name for name, got, want in cases if got is not want]
    for name in bad:
        print(f"  x {name}", file=sys.stderr)
    print(json.dumps({"selftest": len(cases), "failed": bad}, ensure_ascii=False))
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "var/evidence-epistemics.json")
    parser.add_argument("--independence", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    payload = build()
    if args.independence:
        payload["independence"] = independence(payload["rows"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {k: payload[k] for k in ("artifacts_examined", "complete", "by_axis")}
    summary["stale_subject"] = len(payload["stale_subject"])
    summary["empty_quantifier_pass"] = payload["empty_quantifier_pass"]
    if args.independence:
        summary["independence"] = payload["independence"]["witnesses"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
