"""Perspective-safe rendering for structured character information."""

from __future__ import annotations

from .models import Belief


def rewrite_owner_pronouns(claim: str, replacement: str) -> str:
    """Rewrite second-person authored memory into the chosen subject voice."""

    text = str(claim)
    possessive = "我的" if replacement == "我" else f"{replacement}的"
    reflexive = "我自己" if replacement == "我" else f"{replacement}自己"
    return (
        text.replace("你自己", reflexive)
        .replace("你的", possessive)
        .replace("你", replacement)
    )


def render_belief_claim(
    belief: Belief,
    *,
    speaker_id: str,
    owner_name: str,
) -> str:
    """Render an authored memory in first or third person for its speaker."""

    owner_id = str(belief.perspective_owner_id or "")
    if not owner_id:
        return str(belief.claim)
    replacement = "我" if speaker_id == owner_id else owner_name
    return rewrite_owner_pronouns(belief.claim, replacement)


def neutral_belief_claim(belief: Belief, *, owner_name: str) -> str:
    """Render an authored memory with an explicit named subject for storage."""

    if not belief.perspective_owner_id:
        return str(belief.claim)
    return rewrite_owner_pronouns(belief.claim, owner_name)
