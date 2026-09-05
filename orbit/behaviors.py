"""Clean-room policy implementations for the public behavior bundles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class SourceCatalogPolicy:
    """Allow browser actions only when their target is present in source catalog evidence."""

    @staticmethod
    def validate_actions(actions: Iterable[dict[str, str]], catalog: set[str]) -> list[dict[str, str]]:
        validated = list(actions)
        invalid = [action.get("target", "") for action in validated if action.get("target") not in catalog]
        if invalid:
            raise ValueError(f"Actions are not source-backed: {', '.join(invalid)}")
        return validated


@dataclass(frozen=True)
class ImprovementDecision:
    action: str
    stable_runs: int
    reason: str


class ImprovementPolicy:
    """Enforce isolated candidate evaluation, promotion, and rollback gates."""

    REQUIRED_EVALUATIONS = 3
    REQUIRED_SCORECARDS = 7
    MINIMUM_SCORE = 4

    @classmethod
    def assess(
        cls, scores: Iterable[int], stable_runs: int, fingerprint_matches: bool
    ) -> ImprovementDecision:
        values = list(scores)
        if not fingerprint_matches:
            return ImprovementDecision(
                "blocked", 0, "Candidate fingerprint changed outside the isolated patch."
            )
        if len(values) != cls.REQUIRED_SCORECARDS:
            return ImprovementDecision("blocked", 0, "A complete 5+2 evaluation is required.")
        sufficient = all(score >= cls.MINIMUM_SCORE for score in values)
        if sufficient and stable_runs + 1 >= cls.REQUIRED_EVALUATIONS:
            return ImprovementDecision("promote", stable_runs + 1, "Three complete sufficient gates passed.")
        if not sufficient and stable_runs + 1 >= cls.REQUIRED_EVALUATIONS:
            return ImprovementDecision(
                "revert", stable_runs + 1, "Three non-sufficient gates exhausted the candidate."
            )
        return ImprovementDecision(
            "continue", stable_runs + 1, "Candidate remains isolated for another gate."
        )
