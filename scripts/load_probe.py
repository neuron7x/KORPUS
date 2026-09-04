#!/usr/bin/env python3
"""Measure load, spike and soak latency against a running KORPUS deployment.

Distinct corpus questions avoid measuring only the answer cache. Every latency stays
bound to concurrency, target, release and environment class; this is a measurement of
one deployment under declared conditions, never an unqualified throughput claim.
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))
sys.path.insert(0, str(ROOT / "scripts"))
from check_serving_freshness import topology_environment_class  # noqa: E402
from korpus.application.provenance import compute_source_digest  # noqa: E402
from load_probe_lib.metrics import Outcome, refusal_reason  # noqa: E402
from release_identity import release_tag  # noqa: E402

DECLARATION = {
    "given_name": "Навантаження",
    "family_name": "Тестенко",
    "specialty": "перевірка",
}

#: Distinct questions, so the run measures retrieval rather than the answer cache. Drawn
#: from subjects the imported corpus actually holds.
QUESTIONS = (
    "маскування позиції",
    "накладання турнікету",
    "евакуація пораненого",
    "дії при засідці",
    "мінно-вибухове загородження",
    "порядок доповіді командиру",
    "робота з радіостанцією",
    "окоп для стрільби лежачи",
    "балістика польоту кулі",
    "протидія БпЛА засобами РЕБ",
    "розмінування місцевості",
    "організація зв'язку у взводі",
    "спостережний пост обладнання",
    "переправа через водну перешкоду",
    "радіаційний хімічний контроль",
    "штурм окопу дії групи",
)


#: Set when the probe talks to the API directly. Through the edge it is not needed and
#: must not be sent: the point of that path is that the visitor holds nothing.
TOKEN = ""

#: Скільки запитів фази мусять отримати відповідь, щоб числа про затримку описували
#: систему, а не двері. 0.95 — не смак: нижче цього медіана й p95 можуть цілком лежати
#: у відмовах, і тоді звіт міряє швидкість відмови.
ANSWERED_SHARE_FLOOR = 0.95

#: Один токен на робітника, коли їх передали кілька. У режимі `jwt` частку допуску
#: рахують НА СУБ'ЄКТА, а суб'єкт бере з токена. Проба з одним токеном тому міряє
#: одного користувача, що б не стояло в `--concurrency`: виміряно 04.09.2026 — при
#: `KORPUS_MAX_CONCURRENT_ANSWERS=4` (частка суб'єкта 2) паралелізм 4 давав
#: `subject_share_exhausted`, і відмови були властивістю ПРОБИ, а не розгортання,
#: якому оголошено 3–10 РІЗНИХ користувачів. Форма проби мусить збігатися з формою
#: того, що вона нібито міряє.
TOKENS: list[str] = []


def _ask(
    base: str, question: str, timeout: float, token: str | None = None
) -> tuple[float, str, str, str]:
    body = json.dumps({"text": question, "declaration": DECLARATION}).encode("utf-8")
    headers = {"content-type": "application/json"}
    bearer = TOKEN if token is None else token
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    request = urllib.request.Request(f"{base}/v1/answers", data=body, headers=headers)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
        return time.monotonic() - started, "200", str(payload.get("decision_reason", "")), ""
    except urllib.error.HTTPError as error:
        # A refusal is a result. Preserve the server's typed admission reason when it
        # exists so a 503 caused by per-subject isolation is not confused with global
        # capacity exhaustion or an unrelated dependency outage.
        return time.monotonic() - started, str(error.code), "", refusal_reason(error)
    except (OSError, urllib.error.URLError, http.client.HTTPException, TimeoutError) as error:
        # Named rather than blanket: these are what a transport can do to us, each is a
        # data point, and anything else is a defect in this probe that must not be
        # reported as a property of the system under test.
        return time.monotonic() - started, type(error).__name__, "", ""
    except (ValueError, json.JSONDecodeError) as error:
        # A 200 whose body is not the answer schema is a failure of the system, not of
        # the probe, and it is recorded as one rather than crashing the run.
        return time.monotonic() - started, f"malformed:{type(error).__name__}", "", ""


def _phase(base: str, concurrency: int, seconds: float, timeout: float) -> Outcome:
    outcome = Outcome()
    deadline = time.monotonic() + seconds
    counter = 0

    def worker(index: int) -> None:
        nonlocal counter
        token = TOKENS[index % len(TOKENS)] if TOKENS else TOKEN
        while time.monotonic() < deadline:
            counter += 1
            question = QUESTIONS[(index + counter) % len(QUESTIONS)]
            elapsed, status, decision, refusal_reason = _ask(base, question, timeout, token)
            outcome.record(elapsed, status, decision, refusal_reason)
            if status == "429":
                # Honour the refusal instead of spinning on it. A worker that retries a
                # rate limit as fast as it can measures the limiter's reject path and
                # reports a hundred thousand requests the system never agreed to take.
                time.sleep(0.5)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(worker, range(concurrency)))
    return outcome


def _port_of(base: str) -> int | None:
    """Порт із базового URL, або None. Без нього вимір не знав би, що саме він міряв."""
    from urllib.parse import urlparse

    parsed = urlparse(base if "//" in base else f"//{base}")
    return parsed.port


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8081/api")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--spike", type=int, default=24)
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--soak-seconds", type=float, default=60.0)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--out", default="var/load-probe.json")
    parser.add_argument(
        "--environment-class",
        choices=("LOCAL_DEV", "CI_FIXTURE", "PRODUCTION_LIKE", "PRODUCTION"),
        default="LOCAL_DEV",
    )
    parser.add_argument("--source-tree-sha256", default="")
    parser.add_argument("--release", default="")
    parser.add_argument(
        "--token",
        action="append",
        default=None,
        help="bearer token; repeat once per distinct subject the probe should imitate",
    )
    arguments = parser.parse_args()

    global TOKEN, TOKENS  # noqa: PLW0603 - one process, one target, set once at start-up
    TOKENS = [value for value in (arguments.token or []) if value]
    TOKEN = TOKENS[0] if TOKENS else ""

    # Cold first, deliberately: the first question after a restart pays for whatever the
    # process builds lazily, and a report that hides it describes a system nobody starts.
    cold_latency, cold_status, _, cold_refusal_reason = _ask(
        arguments.base, QUESTIONS[0], arguments.timeout
    )

    load = _phase(arguments.base, arguments.concurrency, arguments.seconds, arguments.timeout)
    spike = _phase(arguments.base, arguments.spike, arguments.seconds, arguments.timeout)
    soak = _phase(arguments.base, arguments.concurrency, arguments.soak_seconds, arguments.timeout)

    # Клас середовища НЕ призначається прапорцем угору. Прапорець може лише послабити
    # (CI_FIXTURE), а PRODUCTION_LIKE віддає вимір: чи справді обслуговує оголошена
    # топологія. Доти `--environment-class PRODUCTION` робив прогін на дев-машині
    # доказом про продакшен, і жодна перевірка не питала, чи там щось працює.
    measured = topology_environment_class(ROOT, port=_port_of(arguments.base))
    requested = arguments.environment_class
    environment_class = (
        requested
        if requested not in {"PRODUCTION_LIKE", "PRODUCTION"}
        else measured["environment_class"]
    )
    report = {
        "schema_version": 2,
        "measured_at": datetime.now(UTC).isoformat(),
        "base": arguments.base,
        "environment_class": environment_class,
        "environment_class_requested": requested,
        "environment_class_basis": measured["basis"],
        "source_tree_sha256": arguments.source_tree_sha256 or compute_source_digest(ROOT),
        "release": arguments.release or release_tag(),
        "cold_first_request": {
            "seconds": round(cold_latency, 3),
            "status": cold_status,
            "refusal_reason": cold_refusal_reason,
        },
        # Скільки РІЗНИХ суб'єктів тримала проба. Без цього числа «немає тротлінгу»
        # і «є тротлінг» — твердження про різні світи, і жоден звіт не каже, про який.
        "subjects": max(len(TOKENS), 1),
        "load": {"concurrency": arguments.concurrency, **load.summary()},
        "spike": {"concurrency": arguments.spike, **spike.summary()},
        "soak": {"concurrency": arguments.concurrency, **soak.summary()},
        "drift_p50_seconds": round(
            soak.summary().get("p50_seconds", 0) - load.summary().get("p50_seconds", 0), 3
        ),
        "interpretation": (
            "One machine, one day, with the conditions attached. Non-200 statuses are "
            "results, not failures: 429 is the edge refusing work it was configured to "
            "refuse, and a run where none appear under a spike has not found the "
            "saturation point. Typed refusal_reasons distinguish admission saturation "
            "from unrelated 503s. Latency drift between the load and soak phases is the "
            "number that says whether the steady state is steady."
        ),
    }
    # Проба, яку відмовили НА ДВЕРЯХ, міряє двері. Виміряно 04.09.2026: токени
    # протухли за годину, і прогін дав 101 206 відповідей 401 за хвилину — p95 0.006 с,
    # жодного 5xx, жодного тротлінгу. Тобто ВСІ чотири перевірки SLO пройшли б на
    # вимірі, у якому система не відповіла жодного разу. Порожній знаменник знову
    # виглядав як згода. Виробник відмовляється писати такий звіт: відсутній доказ —
    # це UNKNOWN, а UNKNOWN не є PASS; вигаданий доказ був би гіршим за обидва.
    # Підлога на ЧАСТКУ відповіданих, не на «не нуль». Перша редакція цієї відмови
    # питала лише `> 0`, і незалежний верифікатор показав контрприклад: ОДНА відповідь
    # 200 зі 101 206 проходила сторожа й давала всі тринадцять перевірок гейта
    # надійності зеленими, бо кожне число про затримку бралося з відмов на дверях.
    # Це не «які затримки рейтингувати» — рейтинг лише по 200 теж проходить, бо
    # вибірка з одного елемента дає p95, що дорівнює цьому елементу. Вада на
    # ЗНАМЕННИКУ: майже порожня множина, над якою рахують.
    answered = {phase: report[phase].get("answered_share", 0.0) for phase in ("load", "soak")}
    silent = [phase for phase, share in answered.items() if share < ANSWERED_SHARE_FLOOR]
    if silent:
        print(
            json.dumps(
                {
                    "refused": (
                        f"частка відповіданих нижче {ANSWERED_SHARE_FLOOR:.0%} у фазах, "
                        "за якими судять SLO"
                    ),
                    "phases": silent,
                    "answered_share": {phase: answered[phase] for phase in silent},
                    "statuses": {phase: report[phase]["statuses"] for phase in silent},
                    "why": (
                        "SLO рахуються на фазі soak; прогін, у якому майже все відхилено "
                        "на вході, задовольняє їх усі, нічого не вимірявши"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 65
    path = arguments.out
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
