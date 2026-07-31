from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class CalibrationProfile(BaseModel):
    """Finite-sample acceptance profile for selective answering.

    The profile is only deployment-valid when the Hoeffding upper confidence
    bound on accepted-answer error is below the declared risk limit.
    """

    profile_id: str = Field(min_length=3, max_length=120)
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    accepted_samples: int = Field(ge=0)
    observed_errors: int = Field(ge=0)
    confidence_delta: float = Field(gt=0, lt=1)
    risk_limit: float = Field(gt=0, lt=1)
    minimum_score: float = Field(ge=0, le=1)
    minimum_query_coverage: float = Field(ge=0, le=1)
    minimum_support_score: float = Field(ge=0, le=1)
    minimum_calibration_samples: int = Field(default=200, ge=30)

    @model_validator(mode="after")
    def validate_counts(self) -> "CalibrationProfile":
        if self.observed_errors > self.accepted_samples:
            raise ValueError("observed_errors cannot exceed accepted_samples")
        return self

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
    def deployment_valid(self) -> bool:
        return (
            self.accepted_samples >= self.minimum_calibration_samples
            and self.upper_error_bound <= self.risk_limit
        )

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
