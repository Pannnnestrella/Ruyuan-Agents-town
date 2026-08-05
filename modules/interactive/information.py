"""Perspective-safe rendering for structured character information."""

from __future__ import annotations

from .models import Belief


def rewrite_owner_pronouns(claim: str, replacement: str) -> str:
    """Rewrite authored second-person owner references without touching neutral facts.

    Scenario memories are written to the dossier owner as ``你……``.  The
    ``perspective_owner_id`` marker makes the replacement semantic: an owner
    speaks as ``我``, while another character refers to that owner by name.
    """

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
    """Render one belief for the current speaker while preserving its source."""

    owner_id = str(belief.perspective_owner_id or "")
    if not owner_id:
        return str(belief.claim)
    replacement = "我" if speaker_id == owner_id else owner_name
    return rewrite_owner_pronouns(belief.claim, replacement)


def neutral_belief_claim(belief: Belief, *, owner_name: str) -> str:
    """Return a shareable third-person claim for event and memory storage."""

    if not belief.perspective_owner_id:
        return str(belief.claim)
    return rewrite_owner_pronouns(belief.claim, owner_name)
