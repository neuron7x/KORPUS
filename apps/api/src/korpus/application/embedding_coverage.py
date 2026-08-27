"""Whether the semantic index actually covers the corpus it is asked about.

`span_embeddings` is keyed by (span, model_id) and the retrieval query filters on the
active `model_id` and `dimensions`. That is the right design — a vector from another
model is not a worse match, it is a meaningless one — but it has a consequence nobody
had measured: changing the embedding model does not produce bad results, it produces
*no* results, and the lexical half of the hybrid carries on alone. The answer still
arrives, still cites, and is drawn from a narrower candidate set than the calibrated
profile assumed.

`TECHNICAL_DEBT_V5.md` calls this "embedding backfill/model-migration orchestration and
drift monitoring". The orchestration part is a job; the part that has to exist first is
being able to say, at any moment, which of four states the index is in:

    COMPLETE                  — every span has a vector under the active model.
    BACKFILL_REQUIRED         — spans exist with no vector under the active model.
    MODEL_MIGRATION_REQUIRED  — vectors exist, predominantly under another model id.
    STALE_VECTORS             — a span's text changed after its vector was computed,
                                so the vector describes a passage that is no longer
                                there. Detected by text hash, not by timestamp: a
                                re-extraction that produced identical text is not
                                drift, and a clock is not evidence.

The distinction between the middle two matters operationally. Backfill embeds what is
missing; migration re-embeds what exists under a superseded model and then retires the
old rows. Reporting both as "incomplete" would leave an operator guessing which job to
run, and running the wrong one is expensive at corpus scale.
"""

from __future__ import annotations

from dataclasses import dataclass

from korpus.application.embedding_contracts import validate_embedding_coverage

COMPLETE = "COMPLETE"
BACKFILL_REQUIRED = "BACKFILL_REQUIRED"
MODEL_MIGRATION_REQUIRED = "MODEL_MIGRATION_REQUIRED"
STALE_VECTORS = "STALE_VECTORS"
NO_CORPUS = "NO_CORPUS"


@dataclass(frozen=True)
class EmbeddingCoverage:
    active_model_id: str
    active_dimensions: int
    spans_total: int
    spans_embedded_active: int
    spans_embedded_other_model: int
    spans_stale_text: int
    status: str
    reasons: tuple[str, ...]

    @property
    def coverage_ratio(self) -> float:
        """Fraction of spans the active model can retrieve. Zero corpus is zero, not one.

        Returning 1.0 for an empty corpus would report a complete index over nothing,
        which is the arithmetic that lets a fresh deployment pass a coverage gate.
        """
        if self.spans_total == 0:
            return 0.0
        return self.spans_embedded_active / self.spans_total

    @property
    def complete(self) -> bool:
        return self.status == COMPLETE

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "status": self.status,
            "active_model_id": self.active_model_id,
            "active_dimensions": self.active_dimensions,
            "spans_total": self.spans_total,
            "spans_embedded_active": self.spans_embedded_active,
            "spans_embedded_other_model": self.spans_embedded_other_model,
            "spans_stale_text": self.spans_stale_text,
            "coverage_ratio": round(self.coverage_ratio, 6),
            "reasons": list(self.reasons),
            "interpretation": (
                "Retrieval filters vectors by the active model id, so an incomplete "
                "index does not return worse matches — it returns none, and the "
                "lexical half of the hybrid answers alone from a narrower candidate "
                "set than the calibrated profile assumed."
            ),
        }


def assess_embedding_coverage(
    *,
    active_model_id: str,
    active_dimensions: int,
    spans_total: int,
    spans_embedded_active: int,
    spans_embedded_other_model: int,
    spans_stale_text: int,
) -> EmbeddingCoverage:
    """Classify the index without deciding whether the deployment may run."""

    validate_embedding_coverage(
        active_model_id,
        active_dimensions,
        spans_total,
        spans_embedded_active,
        spans_embedded_other_model,
        spans_stale_text,
    )
    reasons: list[str] = []
    missing = spans_total - spans_embedded_active

    if spans_total == 0:
        status = NO_CORPUS
        reasons.append("no spans exist, so the index covers nothing")
    elif spans_stale_text > 0:
        # Ordered first among the failing states: a stale vector is worse than a
        # missing one. Missing produces silence; stale produces a confident match
        # against text the document no longer contains.
        status = STALE_VECTORS
        reasons.append(
            f"{spans_stale_text} spans have a vector computed from text that has "
            "since changed; those vectors describe passages that are not there"
        )
    elif missing == 0:
        status = COMPLETE
    elif spans_embedded_other_model >= missing:
        status = MODEL_MIGRATION_REQUIRED
        reasons.append(
            f"{spans_embedded_other_model} spans carry vectors under a model other "
            f"than {active_model_id!r}: re-embed and retire the superseded rows"
        )
    else:
        status = BACKFILL_REQUIRED
        reasons.append(f"{missing} spans have no vector under {active_model_id!r}")

    return EmbeddingCoverage(
        active_model_id=active_model_id,
        active_dimensions=active_dimensions,
        spans_total=spans_total,
        spans_embedded_active=spans_embedded_active,
        spans_embedded_other_model=spans_embedded_other_model,
        spans_stale_text=spans_stale_text,
        status=status,
        reasons=tuple(reasons),
    )


def semantic_retrieval_admissible(coverage: EmbeddingCoverage) -> tuple[bool, str]:
    """Whether required-semantic mode may serve against this index.

    `SLO_AND_RELEASE_POLICY_V5.md`: "required semantic mode never silently falls back".
    An index that cannot answer must therefore refuse, not degrade — the degraded
    answer is indistinguishable from a good one at the point of reading.
    """
    if coverage.complete:
        return True, "every span is retrievable under the active model"
    return False, (
        f"semantic retrieval is required but the index is {coverage.status}: "
        + ("; ".join(coverage.reasons) or "coverage is incomplete")
    )
