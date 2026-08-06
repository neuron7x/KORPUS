#!/usr/bin/env python3
"""Put a mixed workload through the running system and record where it saturates.

SRE-005 and RAG-014 both say the same thing from different directions: the scale evidence
this repository carries was produced against a fixture, and a system that has never been
loaded has never been observed refusing work. The interesting number is not throughput —
it is the point at which latency stops being a queue and starts being a timeout, and what
the system says when it gets there.

Three phases, because they fail differently:

  load   a fixed concurrency, long enough for caches to warm; the steady state
  spike  a step change with no warning; the queue, and whether anything is dropped
  soak   the load phase repeated, to see whether latency drifts upward

The questions are drawn from the corpus's own subjects rather than repeated, because one
question repeated measures the cache and calls it retrieval.

Every number here is a measurement of one machine on one day. It is written down with the
conditions attached — concurrency, corpus size, cold or warm — because a latency without
them is a claim about hardware somebody else has.
"""

from __future__ import annotations

import argparse
import http.client
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

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


@dataclass
class Outcome:
    latencies: list[float] = field(default_factory=list)
    statuses: dict[str, int] = field(default_factory=dict)
    decisions: dict[str, int] = field(default_factory=dict)

    def record(self, seconds: float, status: str, decision: str = "") -> None:
        self.latencies.append(seconds)
        self.statuses[status] = self.statuses.get(status, 0) + 1
        if decision:
            self.decisions[decision] = self.decisions.get(decision, 0) + 1

    def summary(self) -> dict[str, Any]:
        ordered = sorted(self.latencies)
        if not ordered:
            return {"requests": 0}

        def at(fraction: float) -> float:
            index = min(len(ordered) - 1, int(fraction * len(ordered)))
            return round(ordered[index], 3)

        return {
            "requests": len(ordered),
            "p50_seconds": at(0.50),
            "p95_seconds": at(0.95),
            "p99_seconds": at(0.99),
            "max_seconds": round(ordered[-1], 3),
            "mean_seconds": round(statistics.fmean(ordered), 3),
            "statuses": dict(sorted(self.statuses.items())),
            "decisions": dict(sorted(self.decisions.items(), key=lambda item: -item[1])),
        }


#: Set when the probe talks to the API directly. Through the edge it is not needed and
#: must not be sent: the point of that path is that the visitor holds nothing.
TOKEN = ""


def _ask(base: str, question: str, timeout: float) -> tuple[float, str, str]:
    body = json.dumps({"text": question, "declaration": DECLARATION}).encode("utf-8")
    headers = {"content-type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    request = urllib.request.Request(f"{base}/v1/answers", data=body, headers=headers)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
        return time.monotonic() - started, "200", str(payload.get("decision_reason", ""))
    except urllib.error.HTTPError as error:
        # A refusal is a result. 429 is the edge doing its job and belongs in the record
        # as itself, not as a failure — the question is whether it appears under a load
        # a real shift would produce.
        return time.monotonic() - started, str(error.code), ""
    except (OSError, urllib.error.URLError, http.client.HTTPException, TimeoutError) as error:
        # Named rather than blanket: these are what a transport can do to us, each is a
        # data point, and anything else is a defect in this probe that must not be
        # reported as a property of the system under test.
        return time.monotonic() - started, type(error).__name__, ""
    except (ValueError, json.JSONDecodeError) as error:
        # A 200 whose body is not the answer schema is a failure of the system, not of
        # the probe, and it is recorded as one rather than crashing the run.
        return time.monotonic() - started, f"malformed:{type(error).__name__}", ""


def _phase(base: str, concurrency: int, seconds: float, timeout: float) -> Outcome:
    outcome = Outcome()
    deadline = time.monotonic() + seconds
    counter = 0

    def worker(index: int) -> None:
        nonlocal counter
        while time.monotonic() < deadline:
            counter += 1
            question = QUESTIONS[(index + counter) % len(QUESTIONS)]
            elapsed, status, decision = _ask(base, question, timeout)
            outcome.record(elapsed, status, decision)
            if status == "429":
                # Honour the refusal instead of spinning on it. A worker that retries a
                # rate limit as fast as it can measures the limiter's reject path and
                # reports a hundred thousand requests the system never agreed to take.
                time.sleep(0.5)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(worker, range(concurrency)))
    return outcome


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
        "--token", default="", help="bearer token; only for probing the API directly"
    )
    arguments = parser.parse_args()

    global TOKEN  # noqa: PLW0603 - one process, one target, set once at start-up
    TOKEN = arguments.token

    # Cold first, deliberately: the first question after a restart pays for whatever the
    # process builds lazily, and a report that hides it describes a system nobody starts.
    cold_latency, cold_status, _ = _ask(arguments.base, QUESTIONS[0], arguments.timeout)

    load = _phase(arguments.base, arguments.concurrency, arguments.seconds, arguments.timeout)
    spike = _phase(arguments.base, arguments.spike, arguments.seconds, arguments.timeout)
    soak = _phase(arguments.base, arguments.concurrency, arguments.soak_seconds, arguments.timeout)

    report = {
        "schema_version": 1,
        "measured_at": datetime.now(UTC).isoformat(),
        "base": arguments.base,
        "cold_first_request": {"seconds": round(cold_latency, 3), "status": cold_status},
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
            "saturation point. Latency drift between the load and soak phases is the "
            "number that says whether the steady state is steady."
        ),
    }
    path = arguments.out
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
