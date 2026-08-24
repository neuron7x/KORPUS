"""The reference set is drawn from the corpus, frozen, and honest about what it cannot say.

RAG-001: the evaluation dataset was thirty cases written against a fixture, so every
number it produced was a number about the fixture. This one is drawn from the deployed
corpus — 1648 documents, fifty-four strata — and frozen with a content digest so a later
run compares against the same questions rather than against easier ones.

Two findings came out of the first runs against a real library, and both are in the
builder now:

  * a sentence is not unique to one document. Ten cases failed because the judge pinned
    the version it sampled from, and every one of the ten held the sentence in two to
    four versions — a military library is full of the same manual under different names.
    The judge was measuring the corpus's duplication and calling it the system's recall.
  * a table of contents is not a proposition. Its rarest words are "передмова", "вступ",
    "скорочень", which appear in the contents page of every manual, so the question built
    from one is a question nobody asks and the system answers it from another manual's
    contents page — correctly.

Executed 2026-08-07: 151 cases, 151 passed, across retrieval, refusal and adversarial.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATASET = ROOT / "evals/datasets/reference.jsonl"
META = ROOT / "evals/datasets/reference.meta.json"


def _cases() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in DATASET.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_the_set_is_frozen_with_a_digest_over_its_own_cases() -> None:
    """A score compared against a run of a different set is not a comparison."""
    import hashlib

    meta = json.loads(META.read_text(encoding="utf-8"))
    digest = hashlib.sha256()
    for case in _cases():
        digest.update(json.dumps(case, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        digest.update(b"\n")

    assert digest.hexdigest() == meta["content_digest"], (
        "the frozen digest does not match the cases on disk; one of them was edited"
    )


def test_every_stratum_is_represented_and_none_dominates() -> None:
    """One aggregate over fifty-four subjects hides that one of them does not work."""
    cases = _cases()
    strata: dict[str, int] = {}
    for case in cases:
        strata[str(case["stratum"])] = strata.get(str(case["stratum"]), 0) + 1

    assert len(strata) >= 20, f"only {len(strata)} strata: this is not stratified"
    largest = max(strata.values())
    assert largest <= len(cases) // 4, (
        f"one stratum holds {largest} of {len(cases)} cases and would decide the score"
    )


def test_a_retrieval_case_names_every_version_that_holds_its_sentence() -> None:
    """Pinning one version measures the library's duplication, not the system's recall."""
    retrieval = [case for case in _cases() if case["kind"] == "retrieval"]
    assert retrieval, "no retrieval cases"

    for case in retrieval:
        holders = case["must_cite_one_of_if_answered"]
        assert isinstance(holders, list) and holders, case["id"]
        assert case["sampled_from_version"] in holders, case["id"]


def test_refusal_cases_were_verified_absent_rather_than_assumed_absent() -> None:
    """"квантова криптографія" feels absent from a military library until it is not."""
    refusals = [case for case in _cases() if case["kind"] == "refusal"]
    assert refusals, "no refusal cases"

    for case in refusals:
        assert "verified absent" in str(case["note"]), case["id"]


def test_no_case_is_a_table_of_contents() -> None:
    """Its rarest words appear in every manual, so the question is one nobody asks."""
    for case in _cases():
        sentence = str(case.get("evidence_sentence", ""))
        if not sentence:
            continue
        lines = [line for line in sentence.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        # The same predicate the builder applies, stated once here as the property
        # rather than imported: a test that calls the code under test agrees with it by
        # construction.
        numbered = sum(
            1
            for line in lines
            if re.match(r"^\s*\S.*?\s\d{1,4}\s*$", line)
        )
        assert numbered / len(lines) < 0.5, f"{case['id']} is a contents page: {lines[:3]}"


def test_the_set_says_what_it_cannot_judge() -> None:
    """Calling this a gold standard would be the overclaim RAG-003 exists to prevent."""
    meta = json.loads(META.read_text(encoding="utf-8"))

    assert meta["cannot_judge"], "a reference set that claims to judge everything judges nothing"
    text = " ".join(meta["cannot_judge"])
    assert "RAG-003" in text
    assert "annotators" in text
