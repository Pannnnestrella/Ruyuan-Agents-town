"""Importance-aware belief selection for LLM context windows.

Recency-only slicing (``beliefs[-N:]``) silently evicts early key evidence in
long games. Selection here mixes importance with recency: the newest beliefs
always stay (conversation continuity), the remaining slots go to the most
valuable older beliefs, and the final list keeps chronological order so the
model reads a stable timeline.
"""

from __future__ import annotations

from .models import Belief


def belief_importance(belief: Belief, *, current_round: int) -> float:
    """Deterministic value estimate for keeping a belief in context."""

    score = float(belief.confidence)
    if belief.truth_id:
        # Tied to an authored truth or secret: likely case-critical evidence.
        score += 2.0
    if belief.information_type == "fact":
        score += 1.0
    if belief.source_type in {"authored", "observation"}:
        score += 0.5
    if belief.supporting_ids:
        score += 0.5
    age = max(0, int(current_round) - int(belief.learned_round))
    score += max(0.0, 1.0 - 0.25 * age)
    return score


def select_context_beliefs(
    beliefs: list[Belief],
    *,
    current_round: int,
    limit: int,
    recent_keep: int = 8,
) -> list[Belief]:
    """Pick up to ``limit`` beliefs: newest ``recent_keep`` plus top-valued rest."""

    if limit <= 0:
        return []
    if len(beliefs) <= limit:
        return list(beliefs)
    recent_keep = min(recent_keep, limit)
    recent = beliefs[-recent_keep:] if recent_keep else []
    older = beliefs[:-recent_keep] if recent_keep else list(beliefs)
    slots = limit - len(recent)
    ranked = sorted(
        range(len(older)),
        key=lambda index: (
            -belief_importance(older[index], current_round=current_round),
            -index,
        ),
    )[:slots]
    chosen = [older[index] for index in sorted(ranked)]
    return [*chosen, *recent]
