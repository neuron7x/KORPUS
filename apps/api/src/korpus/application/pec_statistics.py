"""Small finite-sample statistics used by PEC offline admission gates."""

from __future__ import annotations

from dataclasses import dataclass

from korpus.application.statistical_bounds import wilson_score_interval


@dataclass(frozen=True, slots=True)
class DirectionalComparison:
    wins: int
    losses: int
    ties: int
    lower_win_probability: float
    upper_win_probability: float

    @property
    def informative_pairs(self) -> int:
        return self.wins + self.losses


def wilson_interval(
    successes: int, total: int, *, z: float = 1.959963984540054
) -> tuple[float, float]:
    return wilson_score_interval(successes, total, z=z)


def paired_direction(candidate: list[float], baseline: list[float]) -> DirectionalComparison:
    if len(candidate) != len(baseline):
        raise ValueError("paired comparison requires equal lengths")
    wins = sum(c < b for c, b in zip(candidate, baseline, strict=True))
    losses = sum(c > b for c, b in zip(candidate, baseline, strict=True))
    ties = len(candidate) - wins - losses
    lower, upper = wilson_interval(wins, wins + losses)
    return DirectionalComparison(wins, losses, ties, lower, upper)
