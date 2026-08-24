"""Content-addressed Predictive Evidence Control profile schema.

Profiles are learned/promoted offline. Runtime only validates and interprets a bounded
rule list.  A profile has no authority to alter answer thresholds or source evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from korpus.application.evidence_state import FEATURE_NAMES, feature_schema_sha256

ActionName = Literal[
    "STOP_USE_CURRENT_EVIDENCE",
    "PLAN_QUERY_VARIANTS",
    "ENABLE_SEMANTIC_RETRIEVAL",
    "PLAN_AND_SEMANTIC",
    "ABSTAIN",
]
Operator = Literal["lt", "le", "gt", "ge", "eq", "ne"]


class FeatureRange(BaseModel):
    model_config = ConfigDict(frozen=True)
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def valid_range(self) -> FeatureRange:
        for label, value in (("minimum", self.minimum), ("maximum", self.maximum)):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"feature support {label} must be finite")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("feature support minimum cannot exceed maximum")
        return self


class RuleCondition(BaseModel):
    model_config = ConfigDict(frozen=True)
    feature: str
    operator: Operator
    value: float | int | bool | str

    @model_validator(mode="after")
    def known_feature(self) -> RuleCondition:
        if self.feature not in FEATURE_NAMES:
            raise ValueError(f"unknown PEC feature: {self.feature}")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("numeric PEC rule condition must be finite")
        return self


class ControllerLeaf(BaseModel):
    model_config = ConfigDict(frozen=True)
    leaf_id: str = Field(min_length=1, max_length=120)
    action: ActionName
    admitted: bool
    observed_samples: int = Field(ge=0)
    upper_error_bound: float = Field(ge=0.0, le=1.0)
    support: dict[str, FeatureRange] = Field(default_factory=dict)

    @model_validator(mode="after")
    def known_support_features(self) -> ControllerLeaf:
        unknown = set(self.support) - set(FEATURE_NAMES)
        if unknown:
            raise ValueError(f"unknown PEC support feature(s): {sorted(unknown)}")
        return self


class ControllerRule(BaseModel):
    model_config = ConfigDict(frozen=True)
    rule_id: str = Field(min_length=1, max_length=120)
    conditions: tuple[RuleCondition, ...] = ()
    leaf: ControllerLeaf


class ControllerProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = Field(default=2, ge=2, le=2)
    profile_id: str = Field(min_length=3, max_length=120)
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    system_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    evaluation_protocol_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    replay_receipt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    training_receipt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    feature_schema_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    corpus_release_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    answer_calibration_id: str = Field(min_length=3, max_length=120)
    admission_status: Literal["PASS", "FAIL", "UNKNOWN"] = "UNKNOWN"
    controller_risk_limit: float = Field(gt=0.0, lt=1.0)
    minimum_leaf_samples: int = Field(default=30, ge=1)
    rules: tuple[ControllerRule, ...]
    fallback_action: Literal["BASELINE"] = "BASELINE"

    @model_validator(mode="after")
    def validate_profile(self) -> ControllerProfile:
        if self.feature_schema_sha256 != feature_schema_sha256():
            raise ValueError("PEC feature schema digest mismatch")
        rule_ids = [rule.rule_id for rule in self.rules]
        leaf_ids = [rule.leaf.leaf_id for rule in self.rules]
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("PEC rule ids must be unique")
        if len(set(leaf_ids)) != len(leaf_ids):
            raise ValueError("PEC leaf ids must be unique")
        for rule in self.rules:
            leaf = rule.leaf
            if leaf.admitted and leaf.observed_samples < self.minimum_leaf_samples:
                raise ValueError("admitted PEC leaf is under minimum sample support")
            if leaf.admitted and leaf.upper_error_bound > self.controller_risk_limit:
                raise ValueError("admitted PEC leaf exceeds controller risk limit")
        return self

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    @classmethod
    def load(cls, path: Path, expected_sha256: str | None = None) -> ControllerProfile:
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if expected_sha256 is not None and actual != expected_sha256:
            raise ValueError("PEC controller profile digest mismatch")
        return cls.model_validate_json(raw)

    def validate_artifact_bindings(
        self,
        *,
        dataset: Path,
        system_manifest: Path,
        evaluation_protocol: Path,
        replay_receipt: Path,
    ) -> None:
        bindings = {
            "dataset": (dataset, self.dataset_sha256),
            "system manifest": (system_manifest, self.system_manifest_sha256),
            "evaluation protocol": (evaluation_protocol, self.evaluation_protocol_sha256),
            "replay receipt": (replay_receipt, self.replay_receipt_sha256),
        }
        for label, (path, expected) in bindings.items():
            if not path.is_file():
                raise ValueError(f"PEC {label} artifact is missing")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"PEC {label} digest mismatch")
