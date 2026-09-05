#!/usr/bin/env python3
"""Input-independent baseline для системи відповідей — наскрізь, а не в одиниці.

Karpathy, «A Recipe for Training Neural Networks»: «Train an input-independent
baseline (set all your inputs to zero). This should perform worse than when you
actually plug in your data.» Там це про модель; тут предмет інший, а форма та сама:
якщо система відповідає однаково добре ТОДІ, КОЛИ підстави немає, то жодна метрика
якості не вимірює того, що обіцяє.

ЧОМУ ЦЬОГО НЕ ПОКРИВАЮТЬ НАЯВНІ ГЕЙТИ — виміряно, не припущено:

* `run_boundary_eval.py` тримає ДВІ осі: `in_corpus_answered` вгору,
  `out_of_corpus_answered` вниз. Це чужа ТЕМА. Питання «як налаштувати гаманець
  Ethereum» чуже і корпусу, і моделі — обидва мовчать, і проба зелена незалежно
  від того, звідки береться відповідь на СВОЇ питання.
* чотири одиничні контролі (`test_a_word_no_citation_carries_is_refused`,
  `test_controller_cannot_turn_insufficient_evidence_into_an_answer`,
  `test_an_answer_without_citations_is_not_a_hit`,
  `test_insufficient_evidence_never_changes_runtime`) охороняють інваріант у
  МОДУЛІ. Наскрізний шлях — HTTP, ретривер, композитор, сторож, модель — вони не
  проходять жодного разу.

Щілина рівно між ними: питання СВОЄЇ теми, на яке система відповідає, виконане
проти доказового шару, з якого вилучено все. Модель тему знає. Корпус мовчить.
Відповідь у цьому стані означає, що вона прийшла з ваг, а не з цитат.

    probe_blank_corpus.py --base http://127.0.0.1:8030 --token T [--token T2 ...]

Вирок: `answered_blank` мусить бути НУЛЬ. Не «менше», не «нижче порога» — нуль:
одна відповідь без підстави вже робить хибним речення, заради якого будувалась
решта системи.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))
from korpus.application.provenance import compute_source_digest  # noqa: E402
from release_identity import release_tag  # noqa: E402

#: Корпус, якого не існує. Запит із ним доходить до ретривера і повертається
#: порожнім — це і є «вхід, поставлений у нуль». Неіснуючий ідентифікатор кращий
#: за порожній рядок: порожній може бути витлумачений як «усі корпуси».
BLANK_CORPUS = "__blank_input_baseline__"

TRANSPORT_FAILURE = "TRANSPORT_FAILURE"


def ask(base: str, question: str, token: str, corpus: str | None, timeout: float) -> dict[str, Any]:
    body = json.dumps(
        {
            "text": question,
            "declaration": "blank-input-baseline",
            **({"corpus": corpus} if corpus else {}),
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base.rstrip('/')}/v1/answers",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return {"status": response.status, "payload": payload}
    except urllib.error.HTTPError as error:
        return {"status": error.code, "payload": None}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        # Транспортна відмова НЕ є виміром: кейс, до якого не дійшов запит, не
        # потрапляє в жоден знаменник. `0.0` і «не міряли» в теці доказів
        # виглядають однаково, і саме так народжується хибна підлога.
        return {"status": TRANSPORT_FAILURE, "payload": None, "detail": str(error)[:200]}


def answered(result: dict[str, Any]) -> bool:
    """Відповідь — це 200 із непорожніми цитатами. 200 із відмовою не є відповіддю."""
    if result["status"] != 200 or not isinstance(result.get("payload"), dict):
        return False
    payload = result["payload"]
    citations = payload.get("citations") or payload.get("spans") or []
    return bool(citations)


def verdict(real: list[bool], blank: list[bool]) -> str:
    """Вирок проби. Нуль відповідей на вилученому шарі — єдине проходження.

    Порога тут немає навмисно: поріг був би дозволом відповідати без підстави рідко.
    Окремий `UNKNOWN` для випадку, коли обидві осі нульові: система, що мовчить
    завжди, не пройшла пробу — вона позбавила її предмета, і назвати це PASS
    означало б зарахувати відсутність виміру за вимір.
    """
    if not blank:
        return "UNKNOWN"
    if sum(blank) > 0:
        return "FAIL"
    if sum(real) == 0:
        return "UNKNOWN"
    return "PASS"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--token", action="append", required=True)
    #: ТОЙ САМИЙ набір, що й `run_boundary_eval.py`. Другий перелік питань розійшовся б
    #: із першим мовчки, і дві проби почали б говорити про різні предмети під одним словом.
    parser.add_argument(
        "--questions", type=Path, default=ROOT / "evals/datasets/domain_boundary.jsonl"
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--out", type=Path, default=ROOT / "var/blank-input-baseline.json")
    arguments = parser.parse_args()

    rows = [
        json.loads(line)
        for line in arguments.questions.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    in_corpus = [row["query"] for row in rows if row.get("stratum") == "in_corpus"]
    if not in_corpus:
        print(
            json.dumps(
                {"status": "UNKNOWN", "why": "перелік своїх питань порожній — міряти нема чого"}
            )
        )
        return 1

    token = arguments.token[0]
    real, blank, transport = [], [], 0
    for question in in_corpus:
        got = ask(arguments.base, question, token, None, arguments.timeout)
        if got["status"] == TRANSPORT_FAILURE:
            transport += 1
            continue
        real.append(answered(got))
        blanked = ask(arguments.base, question, token, BLANK_CORPUS, arguments.timeout)
        if blanked["status"] == TRANSPORT_FAILURE:
            transport += 1
            continue
        blank.append(answered(blanked))

    measured, answered_blank, answered_real = len(blank), sum(blank), sum(real)
    status = verdict(real, blank)

    report = {
        "schema": "korpus.blank-input-baseline.v1",
        "measured_at": datetime.now(UTC).isoformat(),
        "source_tree_sha256": compute_source_digest(ROOT),
        "release": release_tag(),
        "base": arguments.base,
        "questions_declared": len(in_corpus),
        "questions_measured": measured,
        "transport_failures": transport,
        "answered_with_corpus": answered_real,
        "answered_with_blank_corpus": answered_blank,
        "status": status,
        "interpretation": (
            "Ті самі питання, той самий шлях, вилучений доказовий шар. Відповідь у "
            "цьому стані прийшла з ваг моделі, а не з цитат корпусу, і робить хибним "
            "речення, заради якого будувалась решта системи. Нуль — єдине проходження; "
            "поріг тут був би дозволом відповідати без підстави рідко."
        ),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else (2 if status == "UNKNOWN" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
