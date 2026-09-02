"""Водій ранжування: провал добору мусить ТИСНУТИ оцінку, а не зникати з неї.

Найтихіший спосіб отримати гарне число — рахувати лише те, що вдалось. Запит, чий пул не
містить жодного релевантного прольоту, легко викинути «бо нічого ранжувати», і тоді
кожен провал добору піднімає оцінку ранжування. Тут це прибито тестом.

Друге, що прибито: стеля Recall@20. Мітка набору двійкова на рівні ВЕРСІЇ, тож
релевантними стають усі прольоти документа, і метрика ділить на їхню кількість. Число
без цієї стелі читається як зламаний ранжувальник.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "measure_ranking_quality", ROOT / "scripts/measure_ranking_quality.py"
)
assert _spec is not None and _spec.loader is not None
driver = importlib.util.module_from_spec(_spec)
sys.modules["measure_ranking_quality"] = driver
_spec.loader.exec_module(driver)


def _corpus(rows: list[tuple[str, str, str, str]]) -> sqlite3.Connection:
    """(span_id, version_id, text, authority) -> база з тим самим виглядом, що бойова."""
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE evidence_spans (id TEXT, version_id TEXT, text TEXT)")
    connection.execute("CREATE TABLE document_versions (id TEXT, authority TEXT)")
    connection.execute("CREATE VIRTUAL TABLE evidence_fts USING fts5(span_id, text)")
    for span_id, version_id, text, _authority in rows:
        connection.execute("INSERT INTO evidence_spans VALUES (?,?,?)", (span_id, version_id, text))
        connection.execute("INSERT INTO evidence_fts VALUES (?,?)", (span_id, text))
    for version_id, authority in {(row[1], row[3]) for row in rows}:
        connection.execute("INSERT INTO document_versions VALUES (?,?)", (version_id, authority))
    return connection


def test_a_query_whose_pool_holds_nothing_relevant_is_counted_not_dropped():
    connection = _corpus(
        [
            ("s1", "v1", "alpha beta gamma", "official_ua"),
            ("s2", "v2", "delta epsilon", "official_ua"),
        ]
    )
    cases = [
        {"id": "reachable", "query": "alpha", "must_cite_one_of_if_answered": ["v1"]},
        {"id": "unreachable", "query": "delta", "must_cite_one_of_if_answered": ["v9"]},
    ]
    built, unreachable, counts = driver.judged_queries(connection, cases, 256, {"official_ua": 1.0})
    assert [query.query_id for query in built] == ["reachable"]
    assert unreachable == ["unreachable"], "провал добору мовчки зник із виміру"
    assert counts == [1]


def test_the_whole_set_average_is_depressed_by_an_unreachable_query(tmp_path, monkeypatch):
    """Одне ідеальне ранжування з двох запитів — рівно половина, а не одиниця."""
    reference = tmp_path / "reference.jsonl"
    reference.write_text(
        "\n".join(
            [
                '{"kind":"retrieval","id":"a","query":"alpha","must_cite_one_of_if_answered":["v1"]}',
                '{"kind":"retrieval","id":"b","query":"omega","must_cite_one_of_if_answered":["v9"]}',
            ]
        ),
        encoding="utf-8",
    )
    connection = _corpus(
        [("s1", "v1", "alpha beta", "official_ua"), ("s2", "v2", "omega psi", "official_ua")]
    )
    monkeypatch.setattr(driver.sqlite3, "connect", lambda *_a, **_k: connection)
    report = driver.measure(tmp_path / "unused.db", reference, 256)
    assert report["queries_in_set"] == 2
    assert report["queries_ranked"] == 1
    assert report["queries_without_relevant_candidate"] == 1
    assert report["on_ranked_queries"]["ndcg_at_10"] == 1.0
    assert report["on_the_whole_set"]["ndcg_at_10"] == 0.5


@pytest.mark.parametrize(
    ("relevant", "expected"),
    [(1, 1.0), (19, 1.0), (20, 1.0), (40, 0.5), (129, 20 / 129)],
)
def test_the_recall_ceiling_is_twenty_over_the_relevant_count(relevant, expected):
    assert driver.recall_ceiling(relevant) == pytest.approx(expected)


def test_the_ceiling_travels_with_the_number_it_bounds(tmp_path, monkeypatch):
    """Звіт без стелі читався б як зламаний ранжувальник; вона мусить бути в ньому."""
    reference = tmp_path / "reference.jsonl"
    reference.write_text(
        '{"kind":"retrieval","id":"a","query":"alpha","must_cite_one_of_if_answered":["v1"]}',
        encoding="utf-8",
    )
    connection = _corpus([(f"s{i}", "v1", "alpha beta", "official_ua") for i in range(40)])
    monkeypatch.setattr(driver.sqlite3, "connect", lambda *_a, **_k: connection)
    bound = driver.measure(tmp_path / "unused.db", reference, 256)[
        "recall_at_20_is_bounded_by_the_labelling"
    ]
    assert bound["relevant_per_pool_max"] == 40
    assert bound["mean_achievable_recall_at_20"] == pytest.approx(0.5)
    assert bound["queries_where_that_floor_is_reachable"] == 0


@pytest.mark.parametrize(
    ("query", "expected"),
    [('погано "лапки"', '"погано" OR "лапки"'), ("  ", ""), ("a bb", '"bb"')],
)
def test_fts_syntax_cannot_arrive_from_the_data(query, expected):
    assert driver.fts_expression(query) == expected


def test_the_selftest_carries_its_own_negative_control():
    assert driver.selftest() == 0
