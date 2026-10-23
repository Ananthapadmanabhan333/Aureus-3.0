"""Pairing module exports."""

from aureus_rv.pairing.engine import (
    PairEligibilityResult,
    align_pair_history_up_to,
    discover_candidate_pairs_at_timestamp,
    evaluate_pair_eligibility,
)

__all__ = [
    "PairEligibilityResult",
    "align_pair_history_up_to",
    "discover_candidate_pairs_at_timestamp",
    "evaluate_pair_eligibility",
]
