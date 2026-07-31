from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from korpus.application.retrieval import BM25Parameters, RetrievalWeights


class CalibrationProfile(BaseModel):
    """Content-addressed deployment profile for ranking and selective answering.

    Two independent gates must pass:
    1. retrieval quality on judged queries;
    2. a finite-sample upper confidence bound for accepted-answer error.
    """

    schema_version: int = Field(default=2, ge=2, le=2)
    profile_id: str = Field(min_length=3, max_length=120)
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    accepted_samples: int = Field(ge=0)
    observed_errors: int = Field(ge=0)
    confidence_delta: float = Field(gt=0, lt=1)
    risk_limit: float = Field(gt=0, lt=1)
    minimum_calibration_samples: int = Field(default=200, ge=30)

    ranking_evaluated_queries: int = Field(default=0, ge=0)
    minimum_ranking_queries: int = Field(default=100, ge=20)
    ndcg_at_10: float = Field(default=0.0, ge=0, le=1)
    mrr_at_10: float = Field(default=0.0, ge=0, le=1)
    recall_at_20: float = Field(default=0.0, ge=0, le=1)
    minimum_ndcg_at_10: float = Field(default=0.70, ge=0, le=1)
    minimum_recall_at_20: float = Field(default=0.85, ge=0, le=1)

    minimum_score: float = Field(ge=0, le=1)
    minimum_query_coverage: float = Field(ge=0, le=1)
    minimum_support_score: float = Field(ge=0, le=1)

    bm25_k1: float = Field(default=1.5, ge=0.1, le=4.0)
    bm25_b: float = Field(default=0.75, ge=0, le=1)
    weight_lexical: float = Field(default=0.42, ge=0, le=1)
    weight_query_coverage: float = Field(default=0.24, ge=0, le=1)
    weight_character: float = Field(default=0.10, ge=0, le=1)
    weight_authority: float = Field(default=0.14, ge=0, le=1)
    weight_phrase: float = Field(default=0.06, ge=0, le=1)
    weight_temporal: float = Field(default=0.04, ge=0, le=1)
    diversity_lambda: float = Field(default=0.82, ge=0, le=1)
    per_version_cap: int = Field(default=2, ge=1, le=8)
    retrieval_candidate_budget: int = Field(default=256, ge=8, le=10_000)
    retrieval_timeout_ms: int = Field(default=1200, ge=10, le=60_000)

    @model_validator(mode="after")
    def validate_profile(self) -> "CalibrationProfile":
        if self.observed_errors > self.accepted_samples:
            raise ValueError("observed_errors cannot exceed accepted_samples")
        self.retrieval_weights  # force convex-weight validation
        self.bm25_parameters
        return self

    @property
    def retrieval_weights(self) -> RetrievalWeights:
        return RetrievalWeights(
            lexical=self.weight_lexical,
            query_coverage=self.weight_query_coverage,
            character=self.weight_character,
            authority=self.weight_authority,
            phrase=self.weight_phrase,
            temporal=self.weight_temporal,
        )

    @property
    def bm25_parameters(self) -> BM25Parameters:
        return BM25Parameters(k1=self.bm25_k1, b=self.bm25_b)

    @property
    def empirical_error(self) -> float:
        if self.accepted_samples == 0:
            return 1.0
        return self.observed_errors / self.accepted_samples

    @property
    def upper_error_bound(self) -> float:
        if self.accepted_samples == 0:
            return 1.0
        radius = math.sqrt(math.log(1 / self.confidence_delta) / (2 * self.accepted_samples))
        return min(1.0, self.empirical_error + radius)

    @property
    def ranking_valid(self) -> bool:
        return (
            self.ranking_evaluated_queries >= self.minimum_ranking_queries
            and self.ndcg_at_10 >= self.minimum_ndcg_at_10
            and self.recall_at_20 >= self.minimum_recall_at_20
        )

    @property
    def selective_answering_valid(self) -> bool:
        return (
            self.accepted_samples >= self.minimum_calibration_samples
            and self.upper_error_bound <= self.risk_limit
        )

    @property
    def deployment_valid(self) -> bool:
        return self.ranking_valid and self.selective_answering_valid

    @classmethod
    def load(cls, path: Path) -> "CalibrationProfile":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def dataset_digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))


class DevelopmentCalibration:
    profile_id = "development-unvalidated"
    minimum_score: float
    minimum_query_coverage: float
    minimum_support_score: float

    def __init__(self, minimum_score: float, minimum_query_coverage: float, minimum_support_score: float) -> None:
        self.minimum_score = minimum_score
        self.minimum_query_coverage = minimum_query_coverage
        self.minimum_support_score = minimum_support_score
