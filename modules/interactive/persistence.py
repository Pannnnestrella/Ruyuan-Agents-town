"""Serialization helpers for interactive game state."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .models import (
    AgentState,
    Belief,
    ConversationRecord,
    EventRecord,
    GamePhase,
    GameState,
    LifeState,
    ItemHistoryEntry,
    Notice,
    ObjectState,
    SecretState,
)


_WRITE_LOCKS: dict[str, threading.RLock] = {}
_WRITE_LOCKS_GUARD = threading.Lock()


def _write_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _WRITE_LOCKS_GUARD:
        return _WRITE_LOCKS.setdefault(key, threading.RLock())


def atomic_write_text(
    path: str | Path,
    content: str,
    *,
    encoding: str = "utf-8",
    retries: int = 10,
) -> Path:
    """Write via a unique sibling file and retry transient Windows file locks."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    )
    lock = _write_lock(destination)
    with lock:
        try:
            temporary.write_text(content, encoding=encoding)
            for attempt in range(max(1, retries)):
                try:
                    os.replace(temporary, destination)
                    return destination
                except PermissionError:
                    if attempt + 1 >= max(1, retries):
                        raise
                    time.sleep(min(0.05 * (2 ** attempt), 0.5))
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return destination


def atomic_write_json(path: str | Path, data: Any) -> Path:
    return atomic_write_text(
        path,
        json.dumps(data, ensure_ascii=False, indent=2),
    )


def game_state_from_dict(data: dict[str, Any]) -> GameState:
    agents: dict[str, AgentState] = {}
    for agent_id, raw in data["agents"].items():
        beliefs = []
        for belief in raw.get("beliefs", []):
            migrated = dict(belief)
            confidence = float(migrated.get("confidence", 0.5))
            migrated.setdefault("confidence_score", max(0, min(5, round(confidence * 5))))
            migrated.setdefault(
                "information_type",
                "testimony" if migrated.get("stance") in {"reported", "overheard"} else "fact",
            )
            migrated.setdefault("source_type", str(migrated.get("stance") or "legacy"))
            if not migrated.get("perspective_owner_id") and "你" in str(
                migrated.get("claim", "")
            ) and (
                str(migrated.get("source", "")).startswith("timeline:")
                or migrated.get("source") in {
                    "凶手记忆", "个人秘密", "个人经历", "往事回忆",
                }
                or migrated.get("source_type") in {
                    "authored_memory", "memory", "private_secret",
                    "private_killer_memory", "personal_experience",
                }
            ):
                migrated["perspective_owner_id"] = agent_id
            beliefs.append(Belief(**migrated))
        raw_life_state = str(raw.get("life_state", ""))
        if not raw_life_state:
            legacy_health = int(raw.get("health", 100))
            raw_life_state = (
                LifeState.DEAD.value if legacy_health <= 0
                else LifeState.INJURED.value if legacy_health <= 70
                else LifeState.ALIVE.value
            )
        if raw_life_state in {"severely_injured", "incapacitated", "dying"}:
            raw_life_state = LifeState.INJURED.value
        agents[agent_id] = AgentState(
            agent_id=raw["agent_id"],
            display_name=raw["display_name"],
            location_id=raw["location_id"],
            life_state=LifeState(raw_life_state),
            conditions=list(raw.get("conditions", [])),
            inventory=list(raw.get("inventory", [])),
            beliefs=beliefs,
            public_role=raw.get("public_role", ""),
            resources=dict(raw.get("resources", {})),
            strategic_plan=dict(raw.get("strategic_plan", {})),
            plan_history=list(raw.get("plan_history", [])),
            score=int(raw.get("score", 0)),
            score_breakdown=list(raw.get("score_breakdown", [])),
            discovered_secret_ids=list(raw.get("discovered_secret_ids", [])),
            state_schema_version=int(raw.get("state_schema_version", 1)),
            identity_state=dict(raw.get("identity_state", {})),
            location_state=dict(raw.get("location_state", {
                "current_area": raw["location_id"],
                "previous_area": None,
                "movement_history": [],
            })),
            inventory_state=dict(raw.get("inventory_state", {
                "held_items": list(raw.get("inventory", [])),
                "exchanged_items": [],
                "publicly_revealed_items": [],
            })),
            information_state=dict(raw.get("information_state", {
                "facts": [
                    belief.belief_id for belief in beliefs
                    if belief.information_type == "fact"
                ],
                "testimonies": [
                    belief.belief_id for belief in beliefs
                    if belief.information_type == "testimony"
                ],
                "hypotheses": [
                    belief.belief_id for belief in beliefs
                    if belief.information_type == "hypothesis"
                ],
                "contradictions": [],
                "unanswered_questions": [],
            })),
            case_model=dict(raw.get("case_model", {})),
            social_model=dict(raw.get("social_model", {})),
            strategy_state=dict(raw.get("strategy_state", raw.get("strategic_plan", {}))),
            personal_tasks=list(raw.get("personal_tasks", [])),
            public_story=dict(raw.get("public_story", {})),
        )
        agents[agent_id].state_schema_version = 2

    objects: dict[str, ObjectState] = {}
    for object_id, raw in data["objects"].items():
        if raw is None:
            continue
        migrated = dict(raw)
        migrated["history"] = [
            ItemHistoryEntry(**entry) for entry in migrated.get("history", [])
        ]
        migrated.setdefault("original_location", migrated.get("location_id"))
        migrated.setdefault("original_holder", migrated.get("holder_id"))
        objects[object_id] = ObjectState(**migrated)

    notices = [Notice(**raw) for raw in data.get("notices", [])]
    events = [EventRecord(**raw) for raw in data.get("events", [])]
    conversations = [
        ConversationRecord(**raw) for raw in data.get("conversations", [])
    ]
    secrets = {
        secret_id: SecretState(**raw)
        for secret_id, raw in data.get("secrets", {}).items()
    }
    legacy_max_rounds = int(data["max_rounds"])
    legacy_action_limit = int(data.get("actions_per_round", 1))
    round_schedule = [
        {
            "round": int(rule.get("round", index)),
            "duration_seconds": int(rule.get("duration_seconds", 0)),
            "major_action_limit": int(
                rule.get("major_action_limit", legacy_action_limit)
            ),
        }
        for index, rule in enumerate(data.get("round_schedule", []), start=1)
    ] or [
        {
            "round": round_number,
            "duration_seconds": 0,
            "major_action_limit": legacy_action_limit,
        }
        for round_number in range(1, legacy_max_rounds + 1)
    ]
    return GameState(
        game_id=data["game_id"],
        scenario_id=data["scenario_id"],
        world_id=data["world_id"],
        round_number=int(data["round_number"]),
        max_rounds=len(round_schedule),
        action_step=int(data.get("action_step", 0)),
        actions_per_round=int(round_schedule[0]["major_action_limit"]),
        round_schedule=round_schedule,
        round_actor_progress={
            str(round_number): {
                str(agent_id): dict(progress)
                for agent_id, progress in dict(round_progress).items()
            }
            for round_number, round_progress in dict(
                data.get("round_actor_progress", {})
            ).items()
        },
        round_runtime=dict(data.get("round_runtime", {})),
        player_agent_id=data.get("player_agent_id"),
        phase=GamePhase(data["phase"]),
        locations=dict(data["locations"]),
        agents=agents,
        objects=objects,
        secrets=secrets,
        notices=notices,
        events=events,
        conversations=conversations,
        used_event_cards=list(data.get("used_event_cards", [])),
        seen_event_cards=list(data.get("seen_event_cards", data.get("used_event_cards", []))),
        suggested_event_cards=list(data.get("suggested_event_cards", [])),
        active_event_card=data.get("active_event_card"),
        suggested_public_intel=list(data.get("suggested_public_intel", [])),
        used_public_intel=list(data.get("used_public_intel", [])),
        public_intel_history=list(data.get("public_intel_history", [])),
        active_public_intel=data.get("active_public_intel"),
        votes=list(data.get("votes", [])),
        final_submissions=dict(data.get("final_submissions", {})),
        model_usage=list(data.get("model_usage", [])),
        flags=dict(data.get("flags", {})),
    )
