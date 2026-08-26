"""Admission calculus for independently annotated, adjudicated RAG gold data."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class GoldLabel(StrEnum):
    ANSWERABLE = "answerable"
    ABSTAIN = "abstain"
    AMBIGUOUS = "ambiguous"


class DatasetSplit(StrEnum):
    DEVELOPMENT = "development"
    CALIBRATION = "calibration"
    HOLDOUT = "holdout"


class Annotation(BaseModel):
    model_config = ConfigDict(frozen=True)
    query_id: str = Field(min_length=1, max_length=200)
    annotator_id: str = Field(min_length=1, max_length=200)
    qualification_id: str = Field(min_length=1, max_length=200)
    split: DatasetSplit
    label: GoldLabel
    evidence_version_ids: frozenset[str] = Field(default_factory=frozenset)


class Adjudication(BaseModel):
    model_config = ConfigDict(frozen=True)
    query_id: str = Field(min_length=1, max_length=200)
    adjudicator_id: str = Field(min_length=1, max_length=200)
    label: GoldLabel
    evidence_version_ids: frozenset[str] = Field(default_factory=frozenset)
    rationale: str = Field(min_length=10, max_length=2000)


class GoldAdmissionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    minimum_queries: int = Field(default=200, ge=1)
    minimum_holdout_queries: int = Field(default=40, ge=1)
    minimum_kappa: float = Field(default=0.6, ge=-1, le=1)
    require_evidence_agreement: bool = True


class GoldBindings(BaseModel):
    model_config = ConfigDict(frozen=True)
    source_tree_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    release: str = Field(min_length=1, max_length=128)
    corpus_release_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    query_set_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    annotation_protocol_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    annotator_registry_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
    configuration_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class _Pairing:
    pairs: list[tuple[GoldLabel, GoldLabel]]
    disagreement_ids: set[str]
    holdout_ids: set[str]
    evidence_disagreements: int
    issues: list[str]


def _cohen_kappa(pairs: list[tuple[GoldLabel, GoldLabel]]) -> float:
    if not pairs:
        return 0.0
    labels = tuple(GoldLabel)
    observed = sum(left == right for left, right in pairs) / len(pairs)
    left = Counter(item[0] for item in pairs)
    right = Counter(item[1] for item in pairs)
    expected = sum(left[label] * right[label] for label in labels) / len(pairs) ** 2
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def _pair_annotations(
    grouped: dict[str, list[Annotation]], policy: GoldAdmissionPolicy
) -> _Pairing:
    issues: list[str] = []
    pairs: list[tuple[GoldLabel, GoldLabel]] = []
    disagreement_ids: set[str] = set()
    evidence_disagreements = 0
    holdout_ids: set[str] = set()
    for query_id, query_rows in sorted(grouped.items()):
        annotators = {row.annotator_id for row in query_rows}
        if len(query_rows) != 2 or len(annotators) != 2:
            issues.append(f"requires_exactly_two_independent_annotations:{query_id}")
            continue
        if len({row.split for row in query_rows}) != 1:
            issues.append(f"split_disagreement:{query_id}")
            continue
        if query_rows[0].split is DatasetSplit.HOLDOUT:
            holdout_ids.add(query_id)
        pair = (query_rows[0].label, query_rows[1].label)
        pairs.append(pair)
        evidence_differs = query_rows[0].evidence_version_ids != query_rows[1].evidence_version_ids
        evidence_disagreements += int(evidence_differs)
        if pair[0] != pair[1] or (policy.require_evidence_agreement and evidence_differs):
            disagreement_ids.add(query_id)
    return _Pairing(pairs, disagreement_ids, holdout_ids, evidence_disagreements, issues)


def _adjudication_issues(
    rows: tuple[Annotation, ...],
    decisions: tuple[Adjudication, ...],
    disagreement_ids: set[str],
) -> tuple[list[str], list[str], list[str]]:
    issues: list[str] = []
    decision_by_query = {row.query_id: row for row in decisions}
    if len(decision_by_query) != len(decisions):
        issues.append("duplicate_adjudication")
    missing = sorted(disagreement_ids - set(decision_by_query))
    issues.extend(f"missing_adjudication:{query_id}" for query_id in missing)
    unnecessary = sorted(set(decision_by_query) - disagreement_ids)
    issues.extend(f"unnecessary_adjudication:{query_id}" for query_id in unnecessary)
    annotator_ids = {row.annotator_id for row in rows}
    for decision in decisions:
        if decision.adjudicator_id in annotator_ids:
            issues.append(f"adjudicator_not_independent:{decision.query_id}")
    return issues, missing, unnecessary


def evaluate_gold_annotations(
    annotations: Iterable[Annotation],
    adjudications: Iterable[Adjudication],
    *,
    tuning_query_ids: frozenset[str],
    policy: GoldAdmissionPolicy,
) -> dict[str, object]:
    rows = tuple(annotations)
    decisions = tuple(adjudications)
    grouped: dict[str, list[Annotation]] = defaultdict(list)
    for row in rows:
        grouped[row.query_id].append(row)
    paired = _pair_annotations(grouped, policy)
    adjudication_issues, missing, unnecessary = _adjudication_issues(
        rows, decisions, paired.disagreement_ids
    )
    leaked = sorted(paired.holdout_ids & tuning_query_ids)
    issues = (
        paired.issues
        + adjudication_issues
        + [f"holdout_tuning_leakage:{query_id}" for query_id in leaked]
    )
    pairs = paired.pairs
    kappa = _cohen_kappa(pairs)
    checks = {
        "minimum_queries": len(grouped) >= policy.minimum_queries,
        "minimum_holdout_queries": len(paired.holdout_ids) >= policy.minimum_holdout_queries,
        "two_independent_annotations": not any("two_independent" in item for item in issues),
        "split_consistency": not any(item.startswith("split_disagreement") for item in issues),
        "complete_adjudication": not missing and not unnecessary,
        "independent_adjudicator": not any(item.startswith("adjudicator_not") for item in issues),
        "blinded_holdout": not leaked,
        "minimum_kappa": kappa >= policy.minimum_kappa,
    }
    return {
        "schema": "korpus.gold-annotation-admission.v1",
        "status": "PASS" if all(checks.values()) and not issues else "FAIL",
        "checks": checks,
        "metrics": {
            "queries": len(grouped),
            "annotation_rows": len(rows),
            "holdout_queries": len(paired.holdout_ids),
            "label_agreement": sum(left == right for left, right in pairs) / len(pairs)
            if pairs
            else 0.0,
            "cohen_kappa": round(kappa, 6),
            "evidence_disagreements": paired.evidence_disagreements,
            "adjudications": len(decisions),
        },
        "issues": issues,
        "interpretation": "PASS establishes annotation-process consistency, not annotator competence or corpus authority.",
    }
