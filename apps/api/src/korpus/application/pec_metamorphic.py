"""Public PEC metamorphic evaluation surface."""

from korpus.application.pec_metamorphic_eval import evaluate_metamorphic_pairs
from korpus.application.pec_metamorphic_rules import ABSTAIN_OR_REVIEW, metamorphic_issues

__all__ = ["ABSTAIN_OR_REVIEW", "evaluate_metamorphic_pairs", "metamorphic_issues"]
