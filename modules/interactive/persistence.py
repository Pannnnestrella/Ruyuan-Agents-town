"""Serialization helpers for interactive game state."""

from __future__ import annotations

from typing import Any

from .models import (
    AgentState,
    Belief,
    EventRecord,
    GamePhase,
    GameState,
    LifeState,
    Notice,
    ObjectState,
    SecretState,
)


def game_state_from_dict(data: dict[str, Any]) -> GameState:
    agents: dict[str, AgentState] = {}
    for agent_id, raw in data["agents"].items():
        beliefs = [Belief(**belief) for belief in raw.get("beliefs", [])]
        agents[agent_id] = AgentState(
            agent_id=raw["agent_id"],
            display_name=raw["display_name"],
            location_id=raw["location_id"],
            health=int(raw.get("health", 100)),
            life_state=LifeState(raw.get("life_state", "alive")),
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
        )

    objects: dict[str, ObjectState] = {}
    for object_id, raw in data["objects"].items():
        if raw is None:
            continue
        objects[object_id] = ObjectState(**raw)

    notices = [Notice(**raw) for raw in data.get("notices", [])]
    events = [EventRecord(**raw) for raw in data.get("events", [])]
    secrets = {
        secret_id: SecretState(**raw)
        for secret_id, raw in data.get("secrets", {}).items()
    }
    return GameState(
        game_id=data["game_id"],
        scenario_id=data["scenario_id"],
        world_id=data["world_id"],
        round_number=int(data["round_number"]),
        max_rounds=int(data["max_rounds"]),
        action_step=int(data.get("action_step", 0)),
        actions_per_round=int(data.get("actions_per_round", 1)),
        player_agent_id=data.get("player_agent_id"),
        phase=GamePhase(data["phase"]),
        locations=dict(data["locations"]),
        agents=agents,
        objects=objects,
        secrets=secrets,
        notices=notices,
        events=events,
        used_event_cards=list(data.get("used_event_cards", [])),
        seen_event_cards=list(data.get("seen_event_cards", data.get("used_event_cards", []))),
        suggested_event_cards=list(data.get("suggested_event_cards", [])),
        active_event_card=data.get("active_event_card"),
        suggested_public_intel=list(data.get("suggested_public_intel", [])),
        used_public_intel=list(data.get("used_public_intel", [])),
        public_intel_history=list(data.get("public_intel_history", [])),
        active_public_intel=data.get("active_public_intel"),
        votes=list(data.get("votes", [])),
        flags=dict(data.get("flags", {})),
    )
