"""Deterministic prompt-context budgeting for interactive agents.

Normal contexts pass through byte-for-byte.  Compression only runs when the
rendered prompt would exceed the configured model budget, so this module does
not silently trade away information during ordinary games.
"""

from __future__ import annotations

import copy
import json
import math
from collections import Counter
from typing import Any


def estimate_tokens(value: str) -> int:
    """Conservative tokenizer-independent estimate for Chinese/English text."""

    ascii_count = sum(1 for character in value if ord(character) < 128)
    non_ascii_count = len(value) - ascii_count
    return max(1, math.ceil(ascii_count / 3.6 + non_ascii_count / 1.05))


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _belief_summary(items: list[Any], removed: list[Any]) -> dict[str, Any]:
    typed = Counter()
    stances = Counter()
    key_points = []
    for raw in removed:
        if not isinstance(raw, dict):
            continue
        typed[str(raw.get("information_type") or raw.get("source_type") or "unknown")] += 1
        stances[str(raw.get("stance") or "unknown")] += 1
        claim = str(raw.get("claim") or "").strip()
        if claim and len(key_points) < 8:
            key_points.append({
                "belief_id": str(raw.get("belief_id") or ""),
                "claim": claim[:180],
                "confidence": raw.get("confidence"),
            })
    return {
        "kind": "older_beliefs",
        "removed_count": len(removed),
        "information_types": dict(typed),
        "stances": dict(stances),
        "key_points": key_points,
        "retained_recent_count": len(items),
    }


def _event_summary(items: list[Any], removed: list[Any]) -> dict[str, Any]:
    event_types = Counter()
    key_points = []
    for raw in removed:
        if isinstance(raw, dict):
            event_types[str(raw.get("event_type") or raw.get("source") or "event")] += 1
            text = str(raw.get("summary") or raw.get("content") or raw.get("shared_claim") or "")
        else:
            event_types["event"] += 1
            text = str(raw)
        if text.strip() and len(key_points) < 6:
            key_points.append(text.strip()[:180])
    return {
        "kind": "older_events",
        "removed_count": len(removed),
        "event_types": dict(event_types),
        "key_points": key_points,
        "retained_recent_count": len(items),
    }


_LIST_POLICIES: tuple[tuple[str, int, str], ...] = (
    ("private_beliefs", 14, "belief"),
    ("personal_memories", 16, "belief"),
    ("private_memories", 12, "belief"),
    ("recent_known_events", 6, "event"),
    ("recent_known_dialogue", 6, "event"),
    ("prior_exchanges", 6, "event"),
    ("pregame_timeline", 8, "event"),
    ("bulletin_posts", 6, "event"),
    ("recent_plan_outcomes", 2, "event"),
)


def _truncate_strings(value: Any, *, limit: int) -> Any:
    if isinstance(value, str):
        return value if len(value) <= limit else f"{value[:limit]}…"
    if isinstance(value, list):
        return [_truncate_strings(item, limit=limit) for item in value]
    if isinstance(value, dict):
        return {key: _truncate_strings(item, limit=limit) for key, item in value.items()}
    return value


def compress_context(
    context: dict[str, Any],
    *,
    target_tokens: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compress older memories/events, then deterministically trim as fallback."""

    original_text = _json_text(context)
    before = estimate_tokens(original_text)
    metadata: dict[str, Any] = {
        "triggered": before > target_tokens,
        "estimated_context_tokens_before": before,
        "estimated_context_tokens_after": before,
        "target_context_tokens": max(1, int(target_tokens)),
        "summaries": [],
        "fallback_trimmed": False,
    }
    if before <= target_tokens:
        return context, metadata

    compacted = copy.deepcopy(context)
    summaries: list[dict[str, Any]] = []
    for key, keep, kind in _LIST_POLICIES:
        items = compacted.get(key)
        if not isinstance(items, list) or len(items) <= keep:
            continue
        removed, retained = items[:-keep], items[-keep:]
        compacted[key] = retained
        summary = (
            _belief_summary(retained, removed)
            if kind == "belief"
            else _event_summary(retained, removed)
        )
        summary["field"] = key
        summaries.append(summary)

    if summaries:
        compacted["context_compression_summary"] = summaries

    # If the structured summaries are still too large, shorten verbose fields.
    for string_limit in (600, 360, 220, 120):
        if estimate_tokens(_json_text(compacted)) <= target_tokens:
            break
        compacted = _truncate_strings(compacted, limit=string_limit)
        metadata["fallback_trimmed"] = True

    # Final deterministic fallback: shrink only known growth lists. Core rules,
    # identity, current observation, secrets and output schema remain intact.
    if estimate_tokens(_json_text(compacted)) > target_tokens:
        for key, _, _ in _LIST_POLICIES:
            items = compacted.get(key)
            if not isinstance(items, list):
                continue
            while len(items) > 2 and estimate_tokens(_json_text(compacted)) > target_tokens:
                del items[0]
            if estimate_tokens(_json_text(compacted)) <= target_tokens:
                break
        metadata["fallback_trimmed"] = True

    after = estimate_tokens(_json_text(compacted))
    metadata["estimated_context_tokens_after"] = after
    metadata["summaries"] = summaries
    metadata["within_budget"] = after <= target_tokens
    return compacted, metadata
