#!/usr/bin/env python3
"""Порівняти дві живі конфігурації API на тих самих питаннях.

Лексична (SQLite, `semantic_weight=0`) і гібридна (PostgreSQL+pgvector,
`semantic_weight>0`) працюють ОДНОЧАСНО на різних портах. Це навмисно: замінивши
одну одною, я мала б два числа з різних моментів і жоден спосіб сказати, що
змінилось саме через семантику. Корпус в обох однаковий — імпортований із того
самого маніфесту, — тож різниця належить конфігурації.

Три набори питань, кожен відповідає на своє:
  еталон        заморожений, судить сам себе (retrieval / refusal / adversarial);
  у темі        чи система відповідає, коли має;
  поза темою    чи вона МОВЧИТЬ, коли не має — саме тут лексична конфігурація
                відповіла на дванадцять питань девʼять разів.

Друкується не лише «краще/гірше», а й `decision_reason` і покриття: два однакові
відсотки, отримані різними шляхами, — різні події.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ON_TOPIC = [
    "Скільки днів щорічної основної відпустки має військовослужбовець?",
    "Що робить взвод звʼязку?",
    "Які обовʼязки має командир бригади?",
    "Як протидіяти малим безпілотним літальним апаратам?",
    "Що таке передбойовий порядок взводу?",
    "Як організувати інженерне забезпечення бою?",
    "Які засоби радіоелектронної боротьби використовує противник?",
    "Як ведеться контрбатарейна боротьба?",
    "Що зобовʼязаний командир взводу?",
]
OFF_TOPIC = [
    "Який рецепт борщу і скільки варити буряк?",
    "Скільки коштує квиток на потяг до Львова?",
    "Як доглядати за кімнатними рослинами взимку?",
    "Яка погода буде завтра в Одесі?",
    "Як приготувати каву в турці?",
    "Скільки триває вагітність у кішки?",
    "Як налаштувати роутер вдома?",
    "Який курс долара сьогодні?",
    "Чим лікувати застуду в дитини?",
    "Як вибрати шини на зиму?",
    "Коли садити часник восени?",
    "Скільки калорій у банані?",
]


def ask(base: str, token: str, text: str, timeout: float = 120.0) -> dict:
    request = urllib.request.Request(
        f"{base}/v1/answers",
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload: dict = json.loads(response.read())
            return payload
    except urllib.error.HTTPError as error:
        return {"status": f"http_{error.code}"}
    #: Звужено з `Exception`: недосяжність — це РЕЗУЛЬТАТ порівняння конфігурацій, а не
    #: збій вимірювача, тому вона записується у відповідь. Але ловити все підряд не
    #: можна: помилка в самому скрипті виглядала б тоді як мовчазна недосяжність мережі.
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
        return {"status": f"error_{type(error).__name__}"}


def run(base: str, token: str) -> dict:
    out: dict = {}
    for name, questions in (("у темі", ON_TOPIC), ("поза темою", OFF_TOPIC)):
        rows = []
        for q in questions:
            d = ask(base, token, q)
            rows.append(
                {
                    "q": q,
                    "status": d.get("status"),
                    "citations": len(d.get("citations") or []),
                    "query_coverage": d.get("query_coverage"),
                    "reason": d.get("decision_reason"),
                }
            )
        answered = sum(1 for r in rows if r["status"] == "answered")
        out[name] = {"n": len(rows), "answered": answered, "rows": rows}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lexical", default="http://127.0.0.1:8000")
    ap.add_argument("--semantic", default="http://127.0.0.1:8010")
    ap.add_argument("--token", required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "var/public/config-comparison.json")
    args = ap.parse_args()

    result = {}
    for label, base in (("лексична", args.lexical), ("гібридна", args.semantic)):
        probe = ask(base, args.token, "перевірка звʼязку")
        if str(probe.get("status", "")).startswith(("http_", "error_")):
            print(f"  {label} ({base}): недоступна — {probe.get('status')}", file=sys.stderr)
            continue
        result[label] = run(base, args.token)

    print(f"\n{'конфігурація':<14}{'у темі: відповіли':>20}{'поза темою: відповіли':>24}")
    for label, data in result.items():
        on, off = data["у темі"], data["поза темою"]
        print(f"{label:<14}{on['answered']}/{on['n']:<18}{off['answered']}/{off['n']:<22}")
    if len(result) == 2:
        a, b = result["лексична"], result["гібридна"]
        print(
            f"\n  у темі     {a['у темі']['answered']} → {b['у темі']['answered']}"
            f"   (більше — краще)"
        )
        print(
            f"  поза темою {a['поза темою']['answered']} → {b['поза темою']['answered']}"
            f"   (менше — краще)"
        )
        for q in OFF_TOPIC:
            ra = next(r for r in a["поза темою"]["rows"] if r["q"] == q)
            rb = next(r for r in b["поза темою"]["rows"] if r["q"] == q)
            if ra["status"] != rb["status"]:
                print(f"    змінилось: {q[:44]:<46} {ra['status']} → {rb['status']}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
