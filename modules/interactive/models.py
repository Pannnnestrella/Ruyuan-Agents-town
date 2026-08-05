"""Serializable domain models for the interactive round engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class LifeState(str, Enum):
    ALIVE = "alive"
    INJURED = "injured"
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
    POISON = "poison"
    TREAT = "treat"
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
    information_type: str = "fact"
    source_type: str = "authored"
    speaker_id: str | None = None
    perspective_owner_id: str | None = None
    learned_location: str | None = None
    witnesses: list[str] = field(default_factory=list)
    confidence_score: int = 3
    supporting_ids: list[str] = field(default_factory=list)
    opposing_ids: list[str] = field(default_factory=list)
    verification_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AgentState:
    agent_id: str
    display_name: str
    location_id: str
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
    state_schema_version: int = 2
    identity_state: dict[str, Any] = field(default_factory=dict)
    location_state: dict[str, Any] = field(default_factory=dict)
    inventory_state: dict[str, Any] = field(default_factory=dict)
    information_state: dict[str, Any] = field(default_factory=dict)
    case_model: dict[str, Any] = field(default_factory=dict)
    social_model: dict[str, Any] = field(default_factory=dict)
    strategy_state: dict[str, Any] = field(default_factory=dict)
    personal_tasks: list[dict[str, Any]] = field(default_factory=list)
    public_story: dict[str, Any] = field(default_factory=dict)

    @property
    def can_act(self) -> bool:
        return self.life_state != LifeState.DEAD

    def to_dict(self, *, include_private: bool = True) -> dict[str, Any]:
        data = asdict(self)
        data["life_state"] = self.life_state.value
        if not include_private:
            for private_key in {
                "beliefs",
                "inventory",
                "strategic_plan",
                "plan_history",
                "score",
                "score_breakdown",
                "discovered_secret_ids",
                "identity_state",
                "location_state",
                "inventory_state",
                "information_state",
                "case_model",
                "social_model",
                "strategy_state",
                "personal_tasks",
                "public_story",
            }:
                data.pop(private_key, None)
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
class ItemHistoryEntry:
    action: str
    round_number: int
    action_step: int = 0
    actor_id: str | None = None
    counterparty_id: str | None = None
    event_id: str | None = None
    from_location: str | None = None
    to_location: str | None = None
    from_holder: str | None = None
    to_holder: str | None = None
    hidden_before: bool = False
    hidden_after: bool = False
    public: bool = False
    witnesses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_UNCHANGED = object()


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
    original_location: str | None = None
    original_holder: str | None = None
    publicly_revealed_to: list[str] = field(default_factory=list)
    authenticity: str = "unknown"
    evidential_value: str = ""
    secret_value: str = ""
    history: list[ItemHistoryEntry] = field(default_factory=list)

    def transition(
        self,
        action: str,
        *,
        round_number: int,
        action_step: int = 0,
        actor_id: str | None = None,
        counterparty_id: str | None = None,
        event_id: str | None = None,
        holder_id: str | None | object = _UNCHANGED,
        location_id: str | None | object = _UNCHANGED,
        hidden: bool | object = _UNCHANGED,
        witnesses: list[str] | None = None,
        public: bool = False,
    ) -> ItemHistoryEntry:
        """Apply one auditable item state transition.

        All runtime holder/location/visibility changes go through this method.
        Initial scenario materialization is the only supported direct assignment.
        """

        before_holder = self.holder_id
        before_location = self.location_id
        before_hidden = self.hidden
        if holder_id is not _UNCHANGED:
            self.holder_id = holder_id  # type: ignore[assignment]
        if location_id is not _UNCHANGED:
            self.location_id = location_id  # type: ignore[assignment]
        if hidden is not _UNCHANGED:
            self.hidden = bool(hidden)
        readers = list(dict.fromkeys(witnesses or []))
        if public:
            self.publicly_revealed_to = list(dict.fromkeys([
                *self.publicly_revealed_to, *readers,
            ]))
        entry = ItemHistoryEntry(
            action=action,
            round_number=round_number,
            action_step=action_step,
            actor_id=actor_id,
            counterparty_id=counterparty_id,
            event_id=event_id,
            from_location=before_location,
            to_location=self.location_id,
            from_holder=before_holder,
            to_holder=self.holder_id,
            hidden_before=before_hidden,
            hidden_after=self.hidden,
            public=public,
            witnesses=readers,
        )
        self.history.append(entry)
        return entry

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
            for private_key in {
                "original_location",
                "original_holder",
                "publicly_revealed_to",
                "authenticity",
                "evidential_value",
                "secret_value",
                "history",
                "discovered_by",
            }:
                data.pop(private_key, None)
        elif viewer_id is not None:
            data["history"] = [
                entry
                for entry in data["history"]
                if viewer_id in entry.get("witnesses", [])
                or viewer_id in {
                    entry.get("actor_id"),
                    entry.get("counterparty_id"),
                }
            ]
            data.pop("original_location", None)
            data.pop("original_holder", None)
            data.pop("publicly_revealed_to", None)
            data.pop("secret_value", None)
            data.pop("discovered_by", None)
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
class ConversationRecord:
    conversation_id: str
    event_id: str
    round_number: int
    action_step: int
    speaker_id: str
    listener_id: str
    content: str
    location_id: str
    witnesses: list[str] = field(default_factory=list)
    shared_information_id: str | None = None
    displayed_object_id: str | None = None
    reply_to_event_id: str | None = None

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
    round_schedule: list[dict[str, int]] = field(default_factory=list)
    round_actor_progress: dict[str, dict[str, dict[str, Any]]] = field(
        default_factory=dict
    )
    round_runtime: dict[str, Any] = field(default_factory=dict)
    player_agent_id: str | None = None
    secrets: dict[str, SecretState] = field(default_factory=dict)
    notices: list[Notice] = field(default_factory=list)
    events: list[EventRecord] = field(default_factory=list)
    conversations: list[ConversationRecord] = field(default_factory=list)
    used_event_cards: list[str] = field(default_factory=list)
    seen_event_cards: list[str] = field(default_factory=list)
    suggested_event_cards: list[dict[str, Any]] = field(default_factory=list)
    active_event_card: str | None = None
    suggested_public_intel: list[dict[str, Any]] = field(default_factory=list)
    used_public_intel: list[str] = field(default_factory=list)
    public_intel_history: list[dict[str, Any]] = field(default_factory=list)
    active_public_intel: str | None = None
    votes: list[dict[str, Any]] = field(default_factory=list)
    final_submissions: dict[str, dict[str, Any]] = field(default_factory=dict)
    model_usage: list[dict[str, Any]] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)

    def rule_for_round(self, round_number: int) -> dict[str, int]:
        """Return the configured timing and action budget for one round.

        ``actions_per_round`` remains as a legacy fallback for older saves and
        third-party scenarios. New scenarios use ``round_schedule`` so later
        rounds may have different durations and action limits.
        """

        for rule in self.round_schedule:
            if int(rule.get("round", 0)) == round_number:
                return {
                    "round": round_number,
                    "duration_seconds": max(
                        0, int(rule.get("duration_seconds", 0))
                    ),
                    "major_action_limit": max(
                        1,
                        int(rule.get(
                            "major_action_limit", self.actions_per_round
                        )),
                    ),
                }
        return {
            "round": round_number,
            "duration_seconds": 0,
            "major_action_limit": max(1, int(self.actions_per_round)),
        }

    def action_limit_for_round(self, round_number: int) -> int:
        return int(self.rule_for_round(round_number)["major_action_limit"])

    def duration_for_round(self, round_number: int) -> int:
        return int(self.rule_for_round(round_number)["duration_seconds"])

    def actor_progress(
        self,
        round_number: int,
        agent_id: str,
    ) -> dict[str, Any]:
        """Return the persistent per-character progress bucket for a round."""

        round_bucket = self.round_actor_progress.setdefault(
            str(round_number), {}
        )
        return round_bucket.setdefault(agent_id, {
            "major_actions_used": 0,
            "scheduled_opportunities": 0,
            "last_action_at": None,
            "next_action_at": 30,
            "currently_resolving": False,
        })

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
            "actions_per_round": self.action_limit_for_round(
                min(self.max_rounds, self.round_number + 1)
            ),
            "round_schedule": [dict(rule) for rule in self.round_schedule],
            "round_runtime": {
                key: value for key, value in self.round_runtime.items()
                if key not in {"pause_tokens", "last_clock_at"}
            },
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
            "actions_per_round": self.action_limit_for_round(
                min(self.max_rounds, self.round_number + 1)
            ),
            "round_schedule": [dict(rule) for rule in self.round_schedule],
            "round_actor_progress": (
                self.round_actor_progress if include_private else {}
            ),
            "round_runtime": (
                dict(self.round_runtime) if include_private else {}
            ),
            "player_agent_id": self.player_agent_id if include_private else None,
            "phase": self.phase.value,
            "locations": self.locations,
            "agents": {
                key: value.to_dict(include_private=include_private)
                for key, value in self.agents.items()
            },
            "objects": {
                key: visible
                for key, value in self.objects.items()
                if (visible := value.to_dict(
                    reveal_hidden=include_private,
                    reveal_metadata=include_private,
                )) is not None
            },
            "secrets": {
                key: value.to_dict() for key, value in self.secrets.items()
            } if include_private else {},
            "notices": [notice.to_dict() for notice in self.notices],
            "events": [
                event.to_dict() for event in self.events
                if include_private or event.public
            ],
            "conversations": [
                conversation.to_dict() for conversation in self.conversations
            ] if include_private else [],
            "used_event_cards": self.used_event_cards,
            "seen_event_cards": self.seen_event_cards,
            "suggested_event_cards": self.suggested_event_cards if include_private else [],
            "active_event_card": self.active_event_card,
            "suggested_public_intel": self.suggested_public_intel if include_private else [],
            "used_public_intel": self.used_public_intel,
            "public_intel_history": self.public_intel_history,
            "active_public_intel": self.active_public_intel,
            "votes": self.votes,
            "final_submissions": self.final_submissions if include_private else {},
            "model_usage": self.model_usage if include_private else [],
            "flags": self.flags if include_private else {},
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
