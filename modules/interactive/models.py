"""Serializable domain models for the interactive round engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class LifeState(str, Enum):
    ALIVE = "alive"
    INJURED = "injured"
    INCAPACITATED = "incapacitated"
    DYING = "dying"
    DEAD = "dead"


class GamePhase(str, Enum):
    INTERVENTION = "intervention"
    READY = "ready"
    RESOLVING = "resolving"
    PLAYER_TURN = "player_turn"
    ROUND_COMPLETE = "round_complete"
    DISCUSSION = "discussion"
    VOTING = "voting"
    FINISHED = "finished"


class ActionType(str, Enum):
    MOVE = "move"
    INVESTIGATE = "investigate"
    TALK = "talk"
    POST_NOTICE = "post_notice"
    TRANSFER = "transfer"
    HIDE = "hide"
    ATTACK = "attack"
    TREAT = "treat"
    ESCAPE = "escape"
    WAIT = "wait"


@dataclass(slots=True)
class Belief:
    belief_id: str
    claim: str
    source: str
    confidence: float = 0.5
    stance: str = "uncertain"
    learned_round: int = 0
    truth_id: str | None = None
    shared_with: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AgentState:
    agent_id: str
    display_name: str
    location_id: str
    health: int = 100
    life_state: LifeState = LifeState.ALIVE
    conditions: list[str] = field(default_factory=list)
    inventory: list[str] = field(default_factory=list)
    beliefs: list[Belief] = field(default_factory=list)
    public_role: str = ""
    resources: dict[str, int] = field(default_factory=dict)
    strategic_plan: dict[str, Any] = field(default_factory=dict)
    plan_history: list[dict[str, Any]] = field(default_factory=list)
    score: int = 0
    score_breakdown: list[dict[str, Any]] = field(default_factory=list)
    discovered_secret_ids: list[str] = field(default_factory=list)

    @property
    def can_act(self) -> bool:
        return (
            self.life_state in {LifeState.ALIVE, LifeState.INJURED}
            and "escaped" not in self.conditions
        )

    def to_dict(self, *, include_private: bool = True) -> dict[str, Any]:
        data = asdict(self)
        data["life_state"] = self.life_state.value
        if not include_private:
            data.pop("beliefs", None)
            data.pop("inventory", None)
            data.pop("strategic_plan", None)
            data.pop("plan_history", None)
            data.pop("score", None)
            data.pop("score_breakdown", None)
            data.pop("discovered_secret_ids", None)
        return data


@dataclass(slots=True)
class SecretState:
    secret_id: str
    owner_id: str
    title: str
    claim: str
    category: str = "personal"
    conceal_score: int = 3
    discovery_score: int = 2
    exposed_to: list[str] = field(default_factory=list)
    publicly_exposed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ObjectState:
    object_id: str
    name: str
    location_id: str | None = None
    holder_id: str | None = None
    hidden: bool = False
    portable: bool = True
    discovered_by: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(
        self,
        *,
        viewer_id: str | None = None,
        reveal_hidden: bool = False,
        reveal_metadata: bool = True,
    ) -> dict[str, Any] | None:
        if self.hidden and not reveal_hidden and viewer_id not in self.discovered_by:
            return None
        data = asdict(self)
        if not reveal_metadata:
            data["metadata"] = {
                key: value
                for key, value in self.metadata.items()
                if key in {"description", "public_description"}
            }
        return data


@dataclass(slots=True)
class Notice:
    notice_id: str
    round_number: int
    publisher: str
    display_author: str
    content: str
    visibility: str = "public"
    location_id: str = "lobby"
    authority: str = "host"
    expires_after_round: int | None = None
    seen_by: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ActionIntent:
    actor_id: str
    action_type: ActionType
    target_id: str | None = None
    location_id: str | None = None
    object_id: str | None = None
    content: str = ""
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["action_type"] = self.action_type.value
        return data


@dataclass(slots=True)
class EventRecord:
    event_id: str
    round_number: int
    event_type: str
    summary: str
    actors: list[str] = field(default_factory=list)
    location_id: str | None = None
    public: bool = False
    witnesses: list[str] = field(default_factory=list)
    cause_event_ids: list[str] = field(default_factory=list)
    state_changes: list[dict[str, Any]] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    action_step: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EventCard:
    card_id: str
    title: str
    category: str
    description: str
    impact_preview: str
    effects: list[dict[str, Any]] = field(default_factory=list)
    preconditions: dict[str, Any] = field(default_factory=dict)
    once: bool = True
    hidden_consequence: str = ""

    def to_dict(self, *, reveal_hidden: bool = False) -> dict[str, Any]:
        if reveal_hidden:
            return asdict(self)
        return {
            "card_id": self.card_id,
            "title": self.title,
            "category": self.category,
            "description": self.description,
            "impact_preview": self.impact_preview,
        }


@dataclass(slots=True)
class GameState:
    game_id: str
    scenario_id: str
    world_id: str
    round_number: int
    max_rounds: int
    phase: GamePhase
    locations: dict[str, dict[str, Any]]
    agents: dict[str, AgentState]
    objects: dict[str, ObjectState]
    action_step: int = 0
    actions_per_round: int = 3
    player_agent_id: str | None = None
    secrets: dict[str, SecretState] = field(default_factory=dict)
    notices: list[Notice] = field(default_factory=list)
    events: list[EventRecord] = field(default_factory=list)
    used_event_cards: list[str] = field(default_factory=list)
    seen_event_cards: list[str] = field(default_factory=list)
    suggested_event_cards: list[dict[str, Any]] = field(default_factory=list)
    active_event_card: str | None = None
    suggested_public_intel: list[dict[str, Any]] = field(default_factory=list)
    used_public_intel: list[str] = field(default_factory=list)
    public_intel_history: list[dict[str, Any]] = field(default_factory=list)
    active_public_intel: str | None = None
    votes: list[dict[str, Any]] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)

    def occupants(self, location_id: str, *, include_dead: bool = True) -> list[str]:
        return [
            agent_id
            for agent_id, agent in self.agents.items()
            if agent.location_id == location_id
            and (include_dead or agent.life_state != LifeState.DEAD)
        ]

    def public_view(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "scenario_id": self.scenario_id,
            "world_id": self.world_id,
            "round_number": self.round_number,
            "max_rounds": self.max_rounds,
            "action_step": self.action_step,
            "actions_per_round": self.actions_per_round,
            "phase": self.phase.value,
            "locations": self.locations,
            "agents": {
                key: value.to_dict(include_private=False)
                for key, value in self.agents.items()
            },
            "objects": {
                key: visible
                for key, value in self.objects.items()
                if (visible := value.to_dict(reveal_metadata=False)) is not None
            },
            "notices": [notice.to_dict() for notice in self.notices],
            "public_intel_history": list(self.public_intel_history),
            "events": [event.to_dict() for event in self.events if event.public],
            "active_event_card": self.active_event_card,
            "active_public_intel": self.active_public_intel,
            "votes": list(self.votes) if self.phase == GamePhase.FINISHED else [],
            "player_controlled": self.player_agent_id is not None,
        }

    def to_dict(self, *, include_private: bool = True) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "scenario_id": self.scenario_id,
            "world_id": self.world_id,
            "round_number": self.round_number,
            "max_rounds": self.max_rounds,
            "action_step": self.action_step,
            "actions_per_round": self.actions_per_round,
            "player_agent_id": self.player_agent_id if include_private else None,
            "phase": self.phase.value,
            "locations": self.locations,
            "agents": {
                key: value.to_dict(include_private=include_private)
                for key, value in self.agents.items()
            },
            "objects": {
                key: value.to_dict(
                    reveal_hidden=include_private,
                    reveal_metadata=include_private,
                )
                for key, value in self.objects.items()
            },
            "secrets": {
                key: value.to_dict() for key, value in self.secrets.items()
            } if include_private else {},
            "notices": [notice.to_dict() for notice in self.notices],
            "events": [event.to_dict() for event in self.events],
            "used_event_cards": self.used_event_cards,
            "seen_event_cards": self.seen_event_cards,
            "suggested_event_cards": self.suggested_event_cards if include_private else [],
            "active_event_card": self.active_event_card,
            "suggested_public_intel": self.suggested_public_intel if include_private else [],
            "used_public_intel": self.used_public_intel,
            "public_intel_history": self.public_intel_history,
            "active_public_intel": self.active_public_intel,
            "votes": self.votes,
            "flags": self.flags,
        }


@dataclass(slots=True)
class RoundResult:
    round_number: int
    events: list[EventRecord]
    rejected_intents: list[dict[str, Any]]
    state: GameState
    action_step: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "action_step": self.action_step,
            "events": [event.to_dict() for event in self.events],
            "rejected_intents": self.rejected_intents,
            "state": self.state.to_dict(),
        }
