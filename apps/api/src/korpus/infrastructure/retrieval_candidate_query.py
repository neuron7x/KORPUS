"""Dialect-specific bounded lexical candidate statement builder."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text as sql_text

from korpus.application.retrieval_math import candidate_terms
from korpus.domain.models import Identity
from korpus.infrastructure import row_mapping


def _candidate_compartment_filter(identity: Identity) -> tuple[str, dict[str, str]]:
    """Відсіки в дешевому доборі — ті самі, що в остаточній проєкції.

    Добір не був діркою в доступі: остаточна проєкція
    (`retrieval_queries.retrievable_projection`) застосовує `compartment_predicate`
    після нього, тож невидимий рядок читачеві не діставався. Він З'ЇДАВ БЮДЖЕТ:
    добір обмежений `LIMIT`, і рядки, яких читач бачити не може, витісняли з
    верхівки ті, які може. Ціна — «недостатньо підстав» про корпус, що має
    відповідь; а порядок видачі ще й повідомляв про існування невидимого.
    """
    compartments = sorted(identity.compartments)
    parameters = {f"compartment_{index}": value for index, value in enumerate(compartments)}
    forbidden = ""
    if compartments:
        placeholders = ",".join(f":{name}" for name in parameters)
        forbidden = f"AND dc.compartment NOT IN ({placeholders})"
    # НЕ корельований підзапит. Форма `NOT EXISTS (... WHERE dc.document_id = d.id)`
    # виражає те саме правило й читається природніше, але прив'язана до `d`, тож
    # SQLite оцінює її НА КОЖЕН повнотекстовий збіг — рівно та вада, через яку
    # перевірку заміщення свого часу винесли в CTE (2.5 с проти бюджету 1200 мс).
    # `test_the_supersession_test_is_not_evaluated_per_matching_span` це ловить.
    clause = (
        "AND d.id NOT IN (SELECT dc.document_id FROM document_compartments dc "
        f"WHERE 1=1 {forbidden})"
    )
    return clause, parameters


def candidate_span_query(
    identity: Identity,
    corpora: frozenset[str],
    as_of: date,
    query: str,
    limit: int,
    dialect: str,
) -> tuple[Any, dict[str, Any]] | None:
    """The full-text candidate statement and its parameters, without a connection.

    Returns None when the query holds no usable term — distinct from a statement that
    matches nothing, because the caller must not open a transaction for it.
    """

    term_specs = candidate_terms(query)
    terms = [value for value, _ in term_specs]
    if not terms:
        return None
    classifications = row_mapping.allowed_classifications(identity.clearance)
    sorted_corpora = tuple(sorted(corpora))
    corpus_placeholders = ",".join(f":corpus_{index}" for index, _ in enumerate(sorted_corpora))
    class_placeholders = ",".join(f":class_{index}" for index, _ in enumerate(classifications))
    parameters: dict[str, Any] = {
        "clearance": int(identity.clearance),
        "as_of": as_of.isoformat(),
        "limit": limit,
    }
    parameters.update({f"corpus_{index}": value for index, value in enumerate(sorted_corpora)})
    parameters.update({f"class_{index}": value for index, value in enumerate(classifications)})
    compartment_clause, compartment_parameters = _candidate_compartment_filter(identity)
    parameters.update(compartment_parameters)
    if dialect == "sqlite":
        match_query = " OR ".join(
            f'"{term.replace(chr(34), chr(34) * 2)}"' + ("*" if prefix else "")
            for term, prefix in term_specs
        )
        parameters["query"] = match_query
        # The supersession test used to be a correlated NOT EXISTS. `ORDER BY bm25`
        # forces every match through it, so on a 116 000-span corpus a five-token
        # question evaluated it 23 626 times — 2.5 s against a 1200 ms budget. The
        # answer that reached the reader was "insufficient evidence": the system said
        # the corpus held nothing when it had not finished looking.
        #
        # Gathered once instead, and anti-joined. Identical rows on every query probed
        # (2026-08-06), 15.8 s of retrieval down to 0.7 s across eight questions.
        statement = sql_text(
            f"""
            WITH superseded AS (
              SELECT DISTINCT sv.supersedes_version_id AS id, sv.document_id AS document_id
              FROM document_versions sv
              WHERE sv.supersedes_version_id IS NOT NULL
                AND sv.review_state = 'approved'
                AND COALESCE(sv.effective_from, sv.publication_date) <= :as_of
                AND (sv.effective_until IS NULL OR sv.effective_until >= :as_of)
                AND (sv.rescinded_at IS NULL OR date(sv.rescinded_at) > :as_of)
            )
            SELECT s.id AS span_id
            FROM evidence_fts f
            JOIN evidence_spans s ON s.id = f.span_id
            JOIN document_versions v ON v.id = s.version_id
            JOIN documents d ON d.id = v.document_id
            WHERE evidence_fts MATCH :query
              AND v.review_state = 'approved'
              AND d.corpus_id IN ({corpus_placeholders})
              AND d.access_tier <= :clearance
              AND d.classification IN ({class_placeholders})
              {compartment_clause}
              AND COALESCE(v.effective_from, v.publication_date) <= :as_of
              AND (v.effective_until IS NULL OR v.effective_until >= :as_of)
              AND (v.rescinded_at IS NULL OR date(v.rescinded_at) > :as_of)
              AND (v.id, v.document_id) NOT IN (SELECT id, document_id FROM superseded)
            ORDER BY bm25(evidence_fts), s.id
            LIMIT :limit
            """
        )
    elif dialect == "postgresql":
        parameters["query"] = " | ".join(
            f"{term}:*" if prefix else term for term, prefix in term_specs
        )
        # Interpolated verbatim so the emitted SQL text is unchanged; it only keeps
        # the repeated bound-parameter cast off the right-hand margin.
        as_of_date = "CAST(:as_of AS date)"
        # Стовпець, не обчислення. Під RLS повнотекстова умова НЕ МОЖЕ стати умовою
        # індексу: `ts_match_vq`, `to_tsvector` і `ts_rank_cd` не leakproof, а безпекові
        # умови стоять рівнем нижче, тож «securely promotable» ця умова не буває ніколи
        # — ні за яких статистик. Отже `to_tsvector('simple', s.text)` рахувався на
        # КОЖНОМУ прольоті. Виміряно 04.09.2026 на пілоті (31 464 прольоти): 3.48 с
        # проти 0.97 с зі збереженим вектором, ті самі span_id на чотирьох питаннях.
        # Міграція 0023 тримає вектор ГЕНЕРОВАНИМ, тож розійтися з текстом він не може.
        vector = "s.search_vector"
        statement = sql_text(
            f"""
            WITH superseded AS (
              SELECT DISTINCT sv.supersedes_version_id AS id, sv.document_id AS document_id
              FROM document_versions sv
              WHERE sv.supersedes_version_id IS NOT NULL
                AND sv.review_state = 'approved'
                AND COALESCE(sv.effective_from, sv.publication_date) <= {as_of_date}
                AND (sv.effective_until IS NULL OR sv.effective_until >= {as_of_date})
                AND (sv.rescinded_at IS NULL OR CAST(sv.rescinded_at AS date) > {as_of_date})
            )
            SELECT s.id AS span_id
            FROM evidence_spans s
            JOIN document_versions v ON v.id = s.version_id
            JOIN documents d ON d.id = v.document_id
            WHERE {vector} @@ to_tsquery('simple', :query)
              AND v.review_state = 'approved'
              AND d.corpus_id IN ({corpus_placeholders})
              AND d.access_tier <= :clearance
              AND d.classification IN ({class_placeholders})
              {compartment_clause}
              AND COALESCE(v.effective_from, v.publication_date) <= {as_of_date}
              AND (v.effective_until IS NULL OR v.effective_until >= {as_of_date})
              AND (v.rescinded_at IS NULL OR CAST(v.rescinded_at AS date) > {as_of_date})
              AND (v.id, v.document_id) NOT IN (SELECT id, document_id FROM superseded)
            ORDER BY ts_rank_cd(
                {vector}, to_tsquery('simple', :query)
            ) DESC, s.id
            LIMIT :limit
            """
        )
    else:
        raise RuntimeError(f"unsupported search dialect: {dialect}")
    return statement, parameters
