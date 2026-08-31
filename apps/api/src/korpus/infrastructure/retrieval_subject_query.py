"""Кандидати за ОГОЛОШЕНИМ предметом документа, а не за збігом слів у тексті.

Лексичний шлях сліпий там, де предмет названо лише в заголовку: для 67 зі 101 ролі
стаття з її обов'язками не містить слів власної ролі, тож документ навіть не стає
кандидатом і переранжувати нічого. Правило й вимір — у `application.declared_subject`.

Предмет не дає права обійти жоден фільтр допуску: та сама схвалена й чинна версія,
той самий гриф, корпус, дата й перевірка заміщення, що в лексичному шляху.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text as sql_text

from korpus.application.declared_subject import subjects_in_question
from korpus.domain.models import Identity
from korpus.infrastructure import row_mapping

__all__ = ["subject_span_query", "subjects_in_question"]


def subject_span_query(
    identity: Identity,
    corpora: frozenset[str],
    as_of: date,
    titles: list[str],
    limit: int,
) -> tuple[Any, dict[str, Any]] | None:
    """Прольоти документів, чий заголовок точно збігся з предметом питання."""

    if not titles:
        return None
    classifications = row_mapping.allowed_classifications(identity.clearance)
    sorted_corpora = tuple(sorted(corpora))
    corpus_placeholders = ",".join(f":corpus_{index}" for index, _ in enumerate(sorted_corpora))
    class_placeholders = ",".join(f":class_{index}" for index, _ in enumerate(classifications))
    title_placeholders = ",".join(f":title_{index}" for index, _ in enumerate(titles))
    parameters: dict[str, Any] = {
        "clearance": int(identity.clearance),
        "as_of": as_of.isoformat(),
        "limit": limit,
    }
    parameters.update({f"corpus_{index}": value for index, value in enumerate(sorted_corpora)})
    parameters.update({f"class_{index}": value for index, value in enumerate(classifications)})
    parameters.update({f"title_{index}": value for index, value in enumerate(titles)})
    statement = sql_text(
        f"""
        SELECT s.id AS span_id
        FROM evidence_spans s
        JOIN document_versions v ON v.id = s.version_id
        JOIN documents d ON d.id = v.document_id
        WHERE d.canonical_title IN ({title_placeholders})
          AND v.review_state = 'approved'
          AND d.corpus_id IN ({corpus_placeholders})
          AND d.access_tier <= :clearance
          AND d.classification IN ({class_placeholders})
          AND COALESCE(v.effective_from, v.publication_date) <= :as_of
          AND (v.effective_until IS NULL OR v.effective_until >= :as_of)
          AND (v.rescinded_at IS NULL OR date(v.rescinded_at) > :as_of)
          AND v.id NOT IN (
            SELECT sv.supersedes_version_id FROM document_versions sv
            WHERE sv.supersedes_version_id IS NOT NULL AND sv.review_state = 'approved'
          )
        ORDER BY s.ordinal, s.id
        LIMIT :limit
        """
    )
    return statement, parameters
