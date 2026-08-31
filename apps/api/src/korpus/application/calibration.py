from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from korpus.application.authority_policy import validate_authority_priors
from korpus.application.retrieval import BM25Parameters, RetrievalWeights
from korpus.application.statistical_bounds import hoeffding_upper_bound
from korpus.domain.models import AuthorityClass


class CalibrationProfile(BaseModel):
    """Content-addressed deployment profile for ranking and selective answering.

    Two independent gates must pass:
    1. retrieval quality on judged queries;
    2. a finite-sample upper confidence bound for accepted-answer error.
    """

    schema_version: int = Field(default=3, ge=3, le=3)
    profile_id: str = Field(min_length=3, max_length=120)
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    system_manifest_sha256: str = Field(default="0" * 64, pattern=r"^[a-f0-9]{64}$")
    evaluation_protocol_sha256: str = Field(default="0" * 64, pattern=r"^[a-f0-9]{64}$")

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
    weight_semantic: float = Field(default=0.0, ge=0, le=1)
    weight_query_coverage: float = Field(default=0.24, ge=0, le=1)
    weight_character: float = Field(default=0.10, ge=0, le=1)
    weight_authority: float = Field(default=0.14, ge=0, le=1)
    weight_phrase: float = Field(default=0.06, ge=0, le=1)
    weight_temporal: float = Field(default=0.04, ge=0, le=1)
    authority_official_ua: float = Field(default=1.00, ge=0, le=1)
    authority_official_allied: float = Field(default=0.92, ge=0, le=1)
    authority_manufacturer: float = Field(default=0.78, ge=0, le=1)
    authority_approved_training: float = Field(default=0.74, ge=0, le=1)
    authority_analytical: float = Field(default=0.46, ge=0, le=1)
    authority_historical: float = Field(default=0.30, ge=0, le=1)
    authority_adversary: float = Field(default=0.00, ge=0, le=1)
    authority_unknown: float = Field(default=0.00, ge=0, le=1)
    #: Наскільки релевантним мусить бути джерело, щоб його КЛАС узагалі щось важив.
    #: Ранг лексикографічний: офіційне джерело б'є аналітичне незалежно від збігу. Це
    #: правильно, поки обидва відповідають на питання, і хибно на хвості, де офіційне
    #: майже нерелевантне. Виміряно 31.08.2026 на еталонному наборі: у 11 випадках із 79
    #: (14 %) вищий клас витісняє помітно кращий збіг, подекуди втричі кращий
    #: (-50.0 проти -15.4 за BM25); у двох це дає читачеві гіршу відповідь.
    #: Частка, не абсолют: шкала оцінки залежить від запиту, тож абсолютний поріг міряв би
    #: довжину питання. Нуль вимикає правило й повертає чисту лексикографію.
    authority_relevance_floor: float = Field(default=0.80, ge=0, le=1)
    diversity_lambda: float = Field(default=0.82, ge=0, le=1)
    per_version_cap: int = Field(default=1, ge=1, le=8)
    retrieval_candidate_budget: int = Field(default=256, ge=8, le=10_000)
    retrieval_timeout_ms: int = Field(default=1200, ge=10, le=60_000)

    @model_validator(mode="after")
    def validate_profile(self) -> CalibrationProfile:
        if self.observed_errors > self.accepted_samples:
            raise ValueError("observed_errors cannot exceed accepted_samples")
        # Reading these properties raises if the weights are not convex or BM25 is
        # out of range. The values are discarded: only the validation runs here.
        _convex_weight_check = self.retrieval_weights
        _bm25_range_check = self.bm25_parameters
        validate_authority_priors(self.authority_priors)
        return self

    @property
    def retrieval_weights(self) -> RetrievalWeights:
        return RetrievalWeights(
            lexical=self.weight_lexical,
            semantic=self.weight_semantic,
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
    def authority_priors(self) -> dict[AuthorityClass, float]:
        return {
            AuthorityClass.OFFICIAL_UA: self.authority_official_ua,
            AuthorityClass.OFFICIAL_ALLIED: self.authority_official_allied,
            AuthorityClass.MANUFACTURER: self.authority_manufacturer,
            AuthorityClass.APPROVED_TRAINING: self.authority_approved_training,
            AuthorityClass.ANALYTICAL: self.authority_analytical,
            AuthorityClass.HISTORICAL: self.authority_historical,
            AuthorityClass.ADVERSARY: self.authority_adversary,
            AuthorityClass.UNKNOWN: self.authority_unknown,
        }

    @property
    def empirical_error(self) -> float:
        if self.accepted_samples == 0:
            return 1.0
        return self.observed_errors / self.accepted_samples

    @property
    def upper_error_bound(self) -> float:
        if self.accepted_samples == 0:
            return 1.0
        return hoeffding_upper_bound(
            self.observed_errors, self.accepted_samples, self.confidence_delta
        )

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
    def load(cls, path: Path, expected_sha256: str | None = None) -> CalibrationProfile:
        raw = path.read_bytes()
        if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError("calibration profile digest mismatch")
        return cls.model_validate_json(raw)

    def validate_artifact_bindings(
        self, *, dataset: Path, system_manifest: Path, evaluation_protocol: Path
    ) -> None:
        bindings = {
            "dataset": (dataset, self.dataset_sha256),
            "system manifest": (system_manifest, self.system_manifest_sha256),
            "evaluation protocol": (evaluation_protocol, self.evaluation_protocol_sha256),
        }
        for label, (path, expected) in bindings.items():
            if not path.is_file():
                raise ValueError(f"calibration {label} artifact is missing")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"calibration {label} digest mismatch")

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

    def __init__(
        self,
        minimum_score: float,
        minimum_query_coverage: float,
        minimum_support_score: float,
    ) -> None:
        self.minimum_score = minimum_score
        self.minimum_query_coverage = minimum_query_coverage
        self.minimum_support_score = minimum_support_score
