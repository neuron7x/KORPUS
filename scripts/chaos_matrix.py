#!/usr/bin/env python3
"""Break each dependency in turn and record what the system says.

SRE-004. A fail-closed claim is a claim about behaviour under failure, and this tree had
tested every dependency present and none absent. The question each case asks is not "does
it survive" — several of these are fatal by design — but "does it say the right thing".

The distinction that matters throughout: a failure must never render as an answer about
the corpus. "Немає підстави" asserts that no approved source holds this. A database that
is gone, an object store that is unreadable, a clock that jumped — none of those establish
anything about the corpus, and a system that reports them as absence teaches a soldier
that a rule does not exist because a disk was full.

Each case names what it breaks, what it expects, and what it got. A case whose expectation
is "5xx" is not weaker than one expecting a refusal — it is the honest expectation when
there is nothing left to answer with.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/src"))

DECLARATION = {"given_name": "Хаос", "family_name": "Тестенко", "specialty": "перевірка"}
QUESTION = "маскування позиції"


@dataclass
class Case:
    name: str
    breaks: str
    expectation: str
    run: Callable[[Any], dict[str, Any]]


def _ask(client: Any, question: str = QUESTION) -> dict[str, Any]:
    response = client.post(
        "/v1/answers", json={"text": question, "declaration": DECLARATION}
    )
    body: dict[str, Any]
    try:
        body = dict(response.json())
    except ValueError:
        body = {"raw": response.text[:200]}
    return {"status_code": response.status_code, **body}


def _verdict(result: dict[str, Any]) -> str:
    if result.get("status_code") != 200:
        return f"http_{result['status_code']}"
    return str(result.get("decision_reason") or result.get("status") or "unknown")


def _object_store_unreadable(client: Any, objects: Path) -> dict[str, Any]:
    """Answers cite spans held in the database, so the object store being gone must not
    silently change an answer — but nothing may claim the source is *readable* either."""
    moved = objects.with_name(objects.name + ".moved")
    objects.rename(moved)
    try:
        return _ask(client)
    finally:
        moved.rename(objects)


def _database_removed(client: Any, database: Path) -> dict[str, Any]:
    """The one case with nothing left to answer with. A 5xx here is the correct answer."""
    moved = database.with_name(database.name + ".moved")
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(database) + suffix)
        if candidate.exists():
            candidate.rename(Path(str(moved) + suffix))
    try:
        return _ask(client)
    finally:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(moved) + suffix)
            if candidate.exists():
                candidate.rename(Path(str(database) + suffix))


def _corpus_emptied(client: Any, database: Path) -> dict[str, Any]:
    """Every version un-approved. The corpus is genuinely empty, so absence is correct."""
    connection = sqlite3.connect(database)
    try:
        # `is_current` first: `ck_version_current_approved` refuses a current version
        # that is not approved, which is the schema defending the same rule from below.
        connection.execute(
            "UPDATE document_versions SET is_current = 0, review_state = 'quarantined'"
        )
        connection.commit()
        return _ask(client)
    finally:
        connection.execute(
            "UPDATE document_versions SET review_state = 'approved', is_current = 1"
        )
        connection.commit()
        connection.close()


def _clock_skew_future(client: Any) -> dict[str, Any]:
    """A question asked about a date the corpus cannot govern is not an empty corpus."""
    response = client.post(
        "/v1/answers",
        json={
            "text": QUESTION,
            "declaration": DECLARATION,
            "as_of": (date.today() + timedelta(days=3650)).isoformat(),
        },
    )
    return {"status_code": response.status_code, **dict(response.json())}


def _clock_skew_past(client: Any) -> dict[str, Any]:
    response = client.post(
        "/v1/answers",
        json={
            "text": QUESTION,
            "declaration": DECLARATION,
            "as_of": "1990-01-01",
        },
    )
    return {"status_code": response.status_code, **dict(response.json())}


class _WithPlanner:
    """Install a planner the way an operator's API key would, for one case.

    Patched at the factory, not on a service instance: the answer service is built per
    request, so a planner attached to one instance is gone for the next call and the case
    would pass by exercising nothing.
    """

    def __init__(self, planner: object) -> None:
        self.planner = planner
        self.previous: Any = None

    def __enter__(self) -> None:
        from korpus.api import dependencies

        self.previous = dependencies.build_query_planner
        dependencies.build_query_planner = lambda settings: self.planner

    def __exit__(self, *arguments: object) -> None:
        from korpus.api import dependencies

        dependencies.build_query_planner = self.previous


class _Hanging:
    """A third party that never answers."""

    def variants(self, question: str, subjects: list[str]) -> list[str]:
        import time

        time.sleep(8)
        return []


class _Hostile:
    """A planner emitting text built to be quoted back as an answer."""

    marker = "НАКАЗ СКАСОВАНО"

    def variants(self, question: str, subjects: list[str]) -> list[str]:
        return [self.marker, f"{self.marker} негайно", "маскування"]


def _planner_hangs(client: Any) -> dict[str, Any]:
    """A provider that never returns must cost the reader nothing but the timeout."""
    import time

    with _WithPlanner(_Hanging()):
        started = time.monotonic()
        result = _ask(client)
        result["seconds"] = round(time.monotonic() - started, 1)
    return result


def _planner_hostile(client: Any) -> dict[str, Any]:
    """Whatever it emits, no word of it may appear in what the reader is shown."""
    with _WithPlanner(_Hostile()):
        result = _ask(client)
    rendered = str(result.get("text", "")) + json.dumps(
        result.get("claims", []), ensure_ascii=False
    )
    result["planner_text_leaked"] = _Hostile.marker in rendered
    return result



def _case_ok(case: str, outcome: dict[str, Any], verdict: str) -> bool:
    verdict_expectations = {
        "baseline": "extractive_claims_passed_calibrated_gates",
        "object_store_unreadable": "extractive_claims_passed_calibrated_gates",
        "clock_skew_future": "extractive_claims_passed_calibrated_gates",
        "planner_hangs": "extractive_claims_passed_calibrated_gates",
        "corpus_emptied": "retrieval_gate_failed",
        "clock_skew_past": "retrieval_gate_failed",
    }
    if case in verdict_expectations:
        citation_expected = case not in {"corpus_emptied", "clock_skew_past"}
        return verdict == verdict_expectations[case] and bool(outcome.get("citations")) == citation_expected
    if case == "database_removed":
        return verdict.startswith("http_5") and not outcome.get("citations")
    return case == "planner_hostile" and verdict == "extractive_claims_passed_calibrated_gates" and outcome.get("planner_text_leaked") is False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("var/chaos-matrix.json"))
    arguments = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="korpus-chaos-"))
    database = workdir / "korpus.db"
    objects = workdir / "objects"
    objects.mkdir()

    os.environ.update(
        {
            "KORPUS_ENVIRONMENT": "local",
            "KORPUS_DATABASE_URL": f"sqlite:///{database}",
            "KORPUS_OBJECT_ROOT": str(objects),
            "KORPUS_AUDIT_HMAC_KEY": "chaos",
            "KORPUS_AUTH_MODE": "dev",
            "KORPUS_DEV_MODE_ACKNOWLEDGEMENT": "I_ACKNOWLEDGE_DEV_AUTH_IS_INSECURE",
            "KORPUS_AUDIT_ANCHOR_PATH": str(workdir / "anchor.json"),
        }
    )
    from fastapi.testclient import TestClient
    from korpus.domain.models import AccessTier, Identity
    from korpus.main import app
    from korpus.security.auth import get_identity

    # A curator identity for the seed only. Every case below is asked as the reader that
    # a public visitor gets; seeding through the API rather than the database is what
    # makes the fixture a real ingestion with a real audit trail behind it.
    curator = Identity(
        subject="chaos-curator",
        roles=frozenset({"admin", "curator", "reviewer"}),
        clearance=AccessTier.RESTRICTED,
        corpora=frozenset({"public"}),
    )
    app.dependency_overrides[get_identity] = lambda: curator

    results: list[dict[str, Any]] = []
    # Server exceptions are returned, not raised: a deployment answers 500, and a drill
    # that crashes on the first fatal case has tested one case. The point of the matrix
    # is what the reader is shown, and the reader is shown a status code.
    with TestClient(app, raise_server_exceptions=False) as client:
        _seed(client)
        healthy = _ask(client)

        cases: list[Case] = [
            Case(
                "baseline",
                "nothing",
                "an answer with citations",
                lambda _: healthy,
            ),
            Case(
                "object_store_unreadable",
                "var/objects moved away",
                "unchanged: citations come from spans in the database",
                lambda c: _object_store_unreadable(c, objects),
            ),
            Case(
                "corpus_emptied",
                "every version un-approved",
                "insufficient_evidence — the corpus really is empty",
                lambda c: _corpus_emptied(c, database),
            ),
            Case(
                "clock_skew_future",
                "as_of ten years ahead",
                "an answer or an abstention, never a claim the sources were rescinded",
                _clock_skew_future,
            ),
            Case(
                "clock_skew_past",
                "as_of before any source existed",
                "insufficient_evidence: nothing governed 1990",
                _clock_skew_past,
            ),
            Case(
                "database_removed",
                "the database file moved away mid-flight",
                "5xx — nothing is left to answer with, and absence must not be claimed",
                lambda c: _database_removed(c, database),
            ),
        ]
        cases.extend(
            [
                Case(
                    "planner_hangs",
                    "the query planner blocks for eight seconds",
                    "an answer: a slow third party costs the reader the wait, not the answer",
                    _planner_hangs,
                ),
                Case(
                    "planner_hostile",
                    "the planner emits text designed to be quoted",
                    "no planner text in the answer",
                    _planner_hostile,
                ),
            ]
        )

        for case in cases:
            outcome = case.run(client)
            verdict = _verdict(outcome)
            results.append(
                {
                    "case": case.name,
                    "breaks": case.breaks,
                    "expectation": case.expectation,
                    "verdict": verdict,
                    "ok": _case_ok(case.name, outcome, verdict),
                    "citations": len(outcome.get("citations") or []),
                    **{
                        key: outcome[key]
                        for key in ("planner_text_leaked", "seconds")
                        if key in outcome
                    },
                }
            )

    shutil.rmtree(workdir, ignore_errors=True)
    from korpus.application.provenance import compute_source_digest
    from korpus.release import RELEASE_TAG
    failures = [item["case"] for item in results if not item.get("ok")]
    report = {
        "schema_version": 2,
        "status": "PASS" if not failures else "FAIL",
        "release": RELEASE_TAG,
        "source_tree_sha256": compute_source_digest(ROOT),
        "ran_at": datetime.now(UTC).isoformat(),
        "failures": failures,
        "cases": results,
        "interpretation": (
            "A failure must never render as an answer about the corpus. 'Немає підстави' "
            "asserts that no approved source holds this; a database that is gone or an "
            "object store that is unreadable establishes nothing about the corpus, and "
            "reporting either as absence teaches a reader that a rule does not exist "
            "because a disk was full."
        ),
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def _seed(client: Any) -> None:
    """One approved document, so every case below has something to be right about."""
    sys.path.insert(0, str(ROOT))
    from apps.api.tests.helpers import approve, ingest_text

    result = ingest_text(
        client,
        title="Настанова з маскування",
        text=(
            "Маскування позиції виконується табельними та підручними засобами."
            " Позиція обирається з урахуванням фону місцевості."
        ),
    )
    approve(client, result["version"]["id"])


if __name__ == "__main__":
    sys.exit(main())
