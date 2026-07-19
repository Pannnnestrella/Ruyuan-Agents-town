"""Deterministic resolver for sequential action phases inside a round."""

from __future__ import annotations

import random
from typing import Iterable

from .models import (
    ActionIntent,
    ActionType,
    EventRecord,
    GamePhase,
    GameState,
    LifeState,
    RoundResult,
)
from .abilities import action_is_authorized, apply_ability


class RoundEngine:
    """Resolve a frozen set of intents against a single game state.

    Agents should produce intents from the same start-of-round snapshot.  This
    resolver then applies them in semantic phases, avoiding legacy iteration
    order from becoming part of the story logic.
    """

    ACTION_ORDER = {
        ActionType.MOVE: 10,
        ActionType.HIDE: 20,
        ActionType.TRANSFER: 30,
        ActionType.INVESTIGATE: 40,
        ActionType.TALK: 50,
        ActionType.POST_NOTICE: 55,
        ActionType.TREAT: 60,
        ActionType.ATTACK: 70,
        ActionType.ESCAPE: 80,
        ActionType.WAIT: 90,
    }

    def __init__(self, *, seed: int = 0):
        self.random = random.Random(seed)
        self._event_sequence = 0

    def resolve_round(
        self,
        state: GameState,
        intents: Iterable[ActionIntent],
    ) -> RoundResult:
        """Compatibility entry point: resolve one phase and close the round.

        New interactive sessions call :meth:`resolve_action_phase` three times so
        a character can move, observe the changed world, and then act again.
        """
        return self.resolve_action_phase(state, intents, finish_round=True)

    def resolve_action_phase(
        self,
        state: GameState,
        intents: Iterable[ActionIntent],
        *,
        finish_round: bool = False,
    ) -> RoundResult:
        if state.phase not in {
            GamePhase.INTERVENTION,
            GamePhase.READY,
            GamePhase.PLAYER_TURN,
            GamePhase.ROUND_COMPLETE,
        }:
            raise ValueError(f"Cannot advance game while phase is {state.phase.value}")
        if state.round_number >= state.max_rounds and state.action_step == 0:
            state.phase = GamePhase.VOTING
            raise ValueError("Game has already reached its final round")

        state.phase = GamePhase.RESOLVING
        active_round = state.round_number + 1
        action_step = state.action_step + 1
        accepted: list[ActionIntent] = []
        rejected: list[dict] = []
        seen_actors: set[str] = set()

        for intent in intents:
            reason = self._validate_intent(state, intent, seen_actors)
            if reason:
                rejected.append({"intent": intent.to_dict(), "reason": reason})
                continue
            accepted.append(intent)
            seen_actors.add(intent.actor_id)

        accepted.sort(key=lambda item: self.ACTION_ORDER[item.action_type])
        round_events: list[EventRecord] = []
        for intent in accepted:
            event = self._resolve_intent(state, intent, active_round)
            event.action_step = action_step
            event.payload.setdefault("action_step", action_step)
            round_events.append(event)

        # Characters without a submitted intent explicitly wait.  This keeps
        # the event history complete and makes stalled agents visible to the director.
        for agent_id, agent in state.agents.items():
            if agent.can_act and agent_id not in seen_actors:
                round_events.append(
                    self._event(
                        active_round,
                        "wait",
                        f"{agent.display_name} 本轮没有采取主要行动。",
                        actors=[agent_id],
                        location_id=agent.location_id,
                        public=True,
                        payload={"action_step": action_step},
                    )
                )
                round_events[-1].action_step = action_step

        state.events.extend(round_events)
        state.action_step = action_step
        round_finished = finish_round or state.action_step >= state.actions_per_round
        if round_finished:
            state.round_number = active_round
            state.action_step = 0
            state.phase = (
                GamePhase.DISCUSSION
                if state.round_number >= state.max_rounds
                else GamePhase.ROUND_COMPLETE
            )
        else:
            state.phase = (
                GamePhase.PLAYER_TURN
                if state.player_agent_id
                else GamePhase.READY
            )
        return RoundResult(active_round, round_events, rejected, state, action_step)

    def resolve_free_action(
        self,
        state: GameState,
        intent: ActionIntent,
    ) -> RoundResult:
        """Resolve player exploration without consuming a major action phase.

        Moving and talking are table-time navigation tools. They change the
        world and memories immediately, but do not make every AI character take
        another major action and do not advance ``action_step``.
        """

        if state.phase not in {GamePhase.READY, GamePhase.PLAYER_TURN}:
            raise ValueError(f"Cannot take a free action while phase is {state.phase.value}")
        if intent.action_type not in {ActionType.MOVE, ActionType.TALK}:
            raise ValueError("Only moving and talking are free exploration actions")
        reason = self._validate_intent(state, intent, set())
        if reason:
            return RoundResult(
                state.round_number + 1,
                [],
                [{"intent": intent.to_dict(), "reason": reason}],
                state,
                state.action_step,
            )
        active_round = state.round_number + 1
        event = self._resolve_intent(state, intent, active_round)
        event.action_step = state.action_step
        event.payload["free_action"] = True
        state.events.append(event)
        return RoundResult(active_round, [event], [], state, state.action_step)

    def _validate_intent(
        self,
        state: GameState,
        intent: ActionIntent,
        seen_actors: set[str],
    ) -> str | None:
        actor = state.agents.get(intent.actor_id)
        if actor is None:
            return "unknown actor"
        if not actor.can_act:
            return f"actor cannot act while {actor.life_state.value}"
        if intent.actor_id in seen_actors:
            return "only one major action is allowed per actor in one action phase"
        if not action_is_authorized(state, intent):
            return "actor does not have the required character ability"
        if intent.action_type == ActionType.MOVE:
            if intent.location_id not in state.locations:
                return "unknown destination"
            if intent.location_id not in state.locations[actor.location_id].get("connections", []):
                return "destination is not connected to actor location"
        if intent.action_type == ActionType.POST_NOTICE:
            if actor.location_id != "lobby":
                return "the bulletin board is in the lobby"
            if not intent.content.strip():
                return "bulletin content cannot be empty"
        if intent.target_id and intent.target_id not in state.agents:
            return "unknown target agent"
        if intent.object_id and intent.object_id not in state.objects:
            return "unknown object"
        return None

    def _resolve_intent(
        self,
        state: GameState,
        intent: ActionIntent,
        round_number: int,
    ) -> EventRecord:
        selected_ability = str(intent.metadata.get("ability_id") or "") or None
        if intent.action_type in {ActionType.ATTACK, ActionType.TREAT}:
            apply_ability(state, intent, selected_ability)
        elif selected_ability:
            apply_ability(state, intent, selected_ability)
        handlers = {
            ActionType.MOVE: self._resolve_move,
            ActionType.INVESTIGATE: self._resolve_investigate,
            ActionType.TALK: self._resolve_talk,
            ActionType.POST_NOTICE: self._resolve_post_notice,
            ActionType.TRANSFER: self._resolve_transfer,
            ActionType.HIDE: self._resolve_hide,
            ActionType.ATTACK: self._resolve_attack,
            ActionType.TREAT: self._resolve_treat,
            ActionType.ESCAPE: self._resolve_escape,
            ActionType.WAIT: self._resolve_wait,
        }
        return handlers[intent.action_type](state, intent, round_number)

    def _resolve_move(self, state: GameState, intent: ActionIntent, round_number: int) -> EventRecord:
        actor = state.agents[intent.actor_id]
        origin = actor.location_id
        origin_witnesses = state.occupants(origin, include_dead=False)
        actor.location_id = intent.location_id or origin
        witnesses = list(dict.fromkeys(
            origin_witnesses + state.occupants(actor.location_id, include_dead=False)
        ))
        return self._event(
            round_number,
            "move",
            f"{actor.display_name} 从{state.locations[origin]['name']}前往{state.locations[actor.location_id]['name']}。",
            actors=[actor.agent_id],
            location_id=actor.location_id,
            public=True,
            witnesses=witnesses,
            state_changes=[{"agent_id": actor.agent_id, "location_id": actor.location_id}],
            payload={"origin_id": origin, "destination_id": actor.location_id},
        )

    def _resolve_investigate(self, state: GameState, intent: ActionIntent, round_number: int) -> EventRecord:
        actor = state.agents[intent.actor_id]
        location_id = intent.location_id or actor.location_id
        if location_id != actor.location_id:
            return self._failed_event(round_number, actor.agent_id, actor.display_name, "调查", "不在目标地点", actor.location_id)
        candidates = [
            item for item in state.objects.values()
            if item.location_id == location_id and actor.agent_id not in item.discovered_by
        ]
        if candidates:
            preferred_tags = {
                str(tag).lower() for tag in intent.metadata.get("search_tags", [])
            }

            def specialty_score(value: Any) -> int:
                tags = {
                    str(tag).lower()
                    for tag in value.metadata.get("tags", [])
                }
                tags.add(str(value.metadata.get("clue_kind", "")).lower())
                return len(preferred_tags.intersection(tags))

            item = sorted(
                candidates,
                key=lambda value: (
                    -specialty_score(value),
                    -int(value.metadata.get("search_priority", 0)),
                    value.object_id,
                ),
            )[0]
            item.discovered_by.append(actor.agent_id)
            clue_claim = str(
                item.metadata.get("clue_claim")
                or item.metadata.get("description")
                or f"{item.name}可能与当前案件有关。"
            )
            return self._event(
                round_number,
                "discovery",
                f"{actor.display_name} 在{state.locations[location_id]['name']}发现了{item.name}。",
                actors=[actor.agent_id],
                location_id=location_id,
                public=True,
                witnesses=state.occupants(location_id, include_dead=False),
                state_changes=[{"object_id": item.object_id, "discovered_by": actor.agent_id}],
                payload={
                    "object_id": item.object_id,
                    "clue_claim": clue_claim,
                    "truth_id": item.metadata.get("truth_id"),
                    "reveals_secret_id": item.metadata.get("reveals_secret_id"),
                    "clue_kind": item.metadata.get("clue_kind", "evidence"),
                    "ability_id": intent.metadata.get("ability_id"),
                    "ability_label": intent.metadata.get("ability_label"),
                },
            )
        return self._event(
            round_number,
            "investigation_empty",
            f"{actor.display_name} 搜查了{state.locations[location_id]['name']}，没有发现新的物品。",
            actors=[actor.agent_id],
            location_id=location_id,
            public=True,
            witnesses=state.occupants(location_id, include_dead=False),
        )

    def _resolve_talk(self, state: GameState, intent: ActionIntent, round_number: int) -> EventRecord:
        actor = state.agents[intent.actor_id]
        target = state.agents.get(intent.target_id or "")
        if target is None or target.location_id != actor.location_id or not target.can_act:
            return self._failed_event(round_number, actor.agent_id, actor.display_name, "交谈", "目标不在场或无法回应", actor.location_id)
        topic = intent.content or "试探对方对当前局势的看法"
        shared_belief = None
        share_belief_id = str(intent.metadata.get("share_belief_id", ""))
        if share_belief_id:
            shared_belief = next(
                (belief for belief in actor.beliefs if belief.belief_id == share_belief_id),
                None,
            )
        if shared_belief and not intent.content.strip():
            topic = f"我愿意把这条情报告诉你：{shared_belief.claim}"
        return self._event(
            round_number,
            "conversation",
            f"{actor.display_name} 对{target.display_name}说：“{topic}”",
            actors=[actor.agent_id, target.agent_id],
            location_id=actor.location_id,
            public=True,
            witnesses=state.occupants(actor.location_id, include_dead=False),
            payload={
                "content": topic,
                "speaker_id": actor.agent_id,
                "listener_id": target.agent_id,
                "shared_belief_id": shared_belief.belief_id if shared_belief else None,
                "shared_claim": shared_belief.claim if shared_belief else None,
                "shared_truth_id": shared_belief.truth_id if shared_belief else None,
                "shared_confidence": shared_belief.confidence if shared_belief else None,
            },
        )

    def _resolve_post_notice(self, state: GameState, intent: ActionIntent, round_number: int) -> EventRecord:
        actor = state.agents[intent.actor_id]
        content = intent.content.strip()[:500]
        return self._event(
            round_number,
            "notice_posted",
            f"{actor.display_name}在客栈大堂公告栏写下：{content}",
            actors=[actor.agent_id],
            location_id="lobby",
            public=True,
            witnesses=state.occupants("lobby", include_dead=False),
            payload={
                "publisher": actor.agent_id,
                "display_author": actor.display_name,
                "content": content,
                "authority": "agent",
            },
        )

    def _resolve_transfer(self, state: GameState, intent: ActionIntent, round_number: int) -> EventRecord:
        actor = state.agents[intent.actor_id]
        target = state.agents.get(intent.target_id or "")
        item = state.objects.get(intent.object_id or "")
        if target is None or target.location_id != actor.location_id:
            return self._failed_event(round_number, actor.agent_id, actor.display_name, "交付物品", "目标不在场", actor.location_id)
        if item is None or item.holder_id != actor.agent_id:
            return self._failed_event(round_number, actor.agent_id, actor.display_name, "交付物品", "并未持有该物品", actor.location_id)
        item.holder_id = target.agent_id
        actor.inventory.remove(item.object_id)
        target.inventory.append(item.object_id)
        return self._event(
            round_number,
            "object_transfer",
            f"{actor.display_name} 将{item.name}交给了{target.display_name}。",
            actors=[actor.agent_id, target.agent_id],
            location_id=actor.location_id,
            public=True,
            witnesses=state.occupants(actor.location_id, include_dead=False),
            state_changes=[{"object_id": item.object_id, "holder_id": target.agent_id}],
        )

    def _resolve_hide(self, state: GameState, intent: ActionIntent, round_number: int) -> EventRecord:
        actor = state.agents[intent.actor_id]
        item = state.objects.get(intent.object_id or "")
        if item is None or item.holder_id != actor.agent_id:
            return self._failed_event(round_number, actor.agent_id, actor.display_name, "藏匿物品", "并未持有该物品", actor.location_id)
        item.holder_id = None
        item.location_id = actor.location_id
        item.hidden = True
        item.discovered_by = [actor.agent_id]
        actor.inventory.remove(item.object_id)
        return self._event(
            round_number,
            "object_hidden",
            f"{actor.display_name} 在{state.locations[actor.location_id]['name']}藏起了一件物品。",
            actors=[actor.agent_id],
            location_id=actor.location_id,
            public=True,
            witnesses=state.occupants(actor.location_id, include_dead=False),
            state_changes=[{"object_id": item.object_id, "hidden": True, "location_id": actor.location_id}],
        )

    def _resolve_attack(self, state: GameState, intent: ActionIntent, round_number: int) -> EventRecord:
        actor = state.agents[intent.actor_id]
        target = state.agents.get(intent.target_id or "")
        if target is None or target.location_id != actor.location_id or target.life_state == LifeState.DEAD:
            return self._failed_event(round_number, actor.agent_id, actor.display_name, "攻击", "目标不在场", actor.location_id)

        base_chance = float(intent.metadata.get("success_chance", 0.7))
        if self.random.random() > max(0.0, min(1.0, base_chance)):
            return self._event(
                round_number,
                "attack_failed",
                f"{actor.display_name} 试图攻击{target.display_name}，但没有得手。",
                actors=[actor.agent_id, target.agent_id],
                location_id=actor.location_id,
                public=True,
                witnesses=state.occupants(actor.location_id),
            )

        damage = max(1, int(intent.metadata.get("damage", 25)))
        target.health = max(0, target.health - damage)
        target.life_state = self._life_state_for_health(target.health)
        condition = intent.metadata.get("condition")
        if condition and condition not in target.conditions:
            target.conditions.append(str(condition))
        return self._event(
            round_number,
            "attack",
            f"{actor.display_name} 攻击了{target.display_name}，后者当前状态为{target.life_state.value}。",
            actors=[actor.agent_id, target.agent_id],
            location_id=actor.location_id,
            public=True,
            witnesses=state.occupants(actor.location_id),
            state_changes=[{
                "agent_id": target.agent_id,
                "health": target.health,
                "life_state": target.life_state.value,
            }],
            payload={
                "damage": damage,
                "ability_id": intent.metadata.get("ability_id"),
                "ability_label": intent.metadata.get("ability_label"),
                "condition": condition,
            },
        )

    def _resolve_treat(self, state: GameState, intent: ActionIntent, round_number: int) -> EventRecord:
        actor = state.agents[intent.actor_id]
        target = state.agents.get(intent.target_id or actor.agent_id)
        if target is None or target.location_id != actor.location_id or target.life_state == LifeState.DEAD:
            return self._failed_event(round_number, actor.agent_id, actor.display_name, "治疗", "目标不在场或已经死亡", actor.location_id)
        amount = max(1, int(intent.metadata.get("amount", 15)))
        before = target.health
        target.health = min(100, target.health + amount)
        target.life_state = self._life_state_for_health(target.health)
        return self._event(
            round_number,
            "treatment",
            f"{actor.display_name} 为{target.display_name}进行了治疗。",
            actors=[actor.agent_id, target.agent_id],
            location_id=actor.location_id,
            public=True,
            witnesses=state.occupants(actor.location_id, include_dead=False),
            state_changes=[{
                "agent_id": target.agent_id,
                "health": target.health,
                "life_state": target.life_state.value,
            }],
            payload={
                "recovered": target.health - before,
                "ability_id": intent.metadata.get("ability_id"),
                "ability_label": intent.metadata.get("ability_label"),
            },
        )

    def _resolve_escape(self, state: GameState, intent: ActionIntent, round_number: int) -> EventRecord:
        actor = state.agents[intent.actor_id]
        location = state.locations[actor.location_id]
        is_front_gate = actor.location_id == "front_gate"
        is_stable_route = actor.location_id == "stable"
        route_open = (
            (is_front_gate and not state.flags.get("front_gate_locked", True))
            or (
                is_stable_route
                and bool(
                    state.flags.get("stable_in_disarray")
                    or state.flags.get("back_exit_open")
                )
            )
        )
        if not route_open:
            return self._event(
                round_number,
                "escape_failed",
                f"{actor.display_name} 试图从{location['name']}离开客栈，但出口封闭且有人看守。",
                actors=[actor.agent_id],
                location_id=actor.location_id,
                public=True,
                witnesses=state.occupants(actor.location_id, include_dead=False),
                payload={"reason": "exit_blocked"},
            )

        if "escaped" not in actor.conditions:
            actor.conditions.append("escaped")
        escaped_agents = state.flags.setdefault("escaped_agents", [])
        if actor.agent_id not in escaped_agents:
            escaped_agents.append(actor.agent_id)
        if actor.agent_id == state.flags.get("killer_id"):
            state.flags["killer_escaped"] = True
        return self._event(
            round_number,
            "escape",
            f"{actor.display_name} 趁乱从{location['name']}脱离客栈，消失在雨幕中。",
            actors=[actor.agent_id],
            location_id=actor.location_id,
            public=True,
            witnesses=state.occupants(actor.location_id, include_dead=False),
            state_changes=[{"agent_id": actor.agent_id, "condition": "escaped"}],
        )

    def _resolve_wait(self, state: GameState, intent: ActionIntent, round_number: int) -> EventRecord:
        actor = state.agents[intent.actor_id]
        return self._event(
            round_number,
            "wait",
            f"{actor.display_name} 留在{state.locations[actor.location_id]['name']}观察局势。",
            actors=[actor.agent_id],
            location_id=actor.location_id,
            public=True,
            witnesses=state.occupants(actor.location_id, include_dead=False),
        )

    @staticmethod
    def _life_state_for_health(health: int) -> LifeState:
        if health <= 0:
            return LifeState.DEAD
        if health <= 15:
            return LifeState.DYING
        if health <= 35:
            return LifeState.INCAPACITATED
        if health <= 70:
            return LifeState.INJURED
        return LifeState.ALIVE

    def _failed_event(
        self,
        round_number: int,
        actor_id: str,
        display_name: str,
        action: str,
        reason: str,
        location_id: str,
    ) -> EventRecord:
        return self._event(
            round_number,
            "action_failed",
            f"{display_name} 尝试{action}，但因{reason}而失败。",
            actors=[actor_id],
            location_id=location_id,
            public=True,
            witnesses=[actor_id],
            payload={"action": action, "reason": reason},
        )

    def _event(
        self,
        round_number: int,
        event_type: str,
        summary: str,
        *,
        actors: list[str] | None = None,
        location_id: str | None = None,
        public: bool = False,
        witnesses: list[str] | None = None,
        state_changes: list[dict] | None = None,
        payload: dict | None = None,
    ) -> EventRecord:
        self._event_sequence += 1
        return EventRecord(
            event_id=f"event-{round_number:02d}-{self._event_sequence:04d}",
            round_number=round_number,
            event_type=event_type,
            summary=summary,
            actors=actors or [],
            location_id=location_id,
            public=public,
            witnesses=witnesses or [],
            state_changes=state_changes or [],
            payload=payload or {},
        )
