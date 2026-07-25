"""Deterministic resolver for sequential action phases inside a round."""

from __future__ import annotations

import random
from typing import Any, Iterable

from .models import (
    ActionIntent,
    ActionType,
    ConversationRecord,
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
        ActionType.TRANSFER: 30,
        ActionType.INVESTIGATE: 40,
        ActionType.TALK: 50,
        ActionType.POST_NOTICE: 55,
        ActionType.TREAT: 60,
        ActionType.POISON: 70,
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
        if action_step == 1:
            round_events.extend(
                self._resolve_pending_poisons(state, active_round, action_step)
            )
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
                        public=False,
                        witnesses=state.occupants(agent.location_id, include_dead=False),
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

        if state.phase not in {
            GamePhase.READY,
            GamePhase.PLAYER_TURN,
            GamePhase.ROUND_COMPLETE,
            GamePhase.DISCUSSION,
        }:
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
        if intent.action_type == ActionType.INVESTIGATE and actor.life_state != LifeState.ALIVE:
            return "injured characters cannot investigate until fully treated"
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
        if intent.action_type in {ActionType.TALK, ActionType.POISON, ActionType.TRANSFER}:
            target = state.agents.get(intent.target_id or "")
            if target is None or target.agent_id == actor.agent_id:
                return "target must be another character"
            if target.location_id != actor.location_id:
                return "target is not in the same location"
        if intent.action_type == ActionType.TALK:
            shared_id = str(intent.metadata.get("share_belief_id") or "")
            if shared_id:
                shared = next(
                    (belief for belief in actor.beliefs if belief.belief_id == shared_id),
                    None,
                )
                if shared is None:
                    return "shared memory does not belong to actor"
                if intent.target_id in shared.shared_with:
                    return "the same memory was already shared with this character"
                shared_fingerprint = self._normalize_dialogue(shared.claim)
                if any(
                    self._normalize_dialogue(known.claim) == shared_fingerprint
                    for known in target.beliefs[-60:]
                ):
                    return "the target already knows equivalent information"
            normalized = self._normalize_dialogue(intent.content)
            if normalized and any(
                event.event_type == "conversation"
                and event.payload.get("speaker_id") == actor.agent_id
                and event.payload.get("listener_id") == intent.target_id
                and self._normalize_dialogue(str(event.payload.get("content") or "")) == normalized
                for event in state.events[-80:]
            ):
                return "the same statement was already made to this character"
        if intent.object_id and intent.object_id not in state.objects:
            return "unknown object"
        if intent.action_type == ActionType.POISON:
            active_round = str(state.round_number + 1)
            poisoned = state.flags.get("poisons_by_round", {}).get(active_round, [])
            if actor.agent_id in poisoned:
                return "each character may attempt at most one poisoning per round"
        return None

    @staticmethod
    def _normalize_dialogue(value: str) -> str:
        text = str(value).strip()
        for _ in range(8):
            previous = text
            for prefix in (
                "我把这条情报告诉你：", "我把这条情报告诉你:",
                "我愿意把这条情报告诉你：", "我愿意把这条情报告诉你:",
                "我愿意分享一条尚未与你核对的信息：",
                "我愿意分享一条尚未与你核对的信息:",
            ):
                if text.startswith(prefix):
                    text = text[len(prefix):].strip()
            for suffix in (
                "。你是否有能相互印证的线索？", "。你有能相互印证的线索吗？",
                "你是否有能相互印证的线索？", "你有能相互印证的线索吗？",
            ):
                if suffix in text:
                    text = text.split(suffix, 1)[0].strip()
            if text == previous:
                break
        compact = "".join(
            character for character in text
            if not character.isspace() and character not in "，。！？；：“”‘’、,.!?;:"
        )
        return compact[:240]

    def _resolve_intent(
        self,
        state: GameState,
        intent: ActionIntent,
        round_number: int,
    ) -> EventRecord:
        selected_ability = str(intent.metadata.get("ability_id") or "") or None
        if intent.action_type in {ActionType.POISON, ActionType.TREAT}:
            apply_ability(state, intent, selected_ability)
        elif selected_ability:
            apply_ability(state, intent, selected_ability)
        handlers = {
            ActionType.MOVE: self._resolve_move,
            ActionType.INVESTIGATE: self._resolve_investigate,
            ActionType.TALK: self._resolve_talk,
            ActionType.POST_NOTICE: self._resolve_post_notice,
            ActionType.TRANSFER: self._resolve_transfer,
            ActionType.POISON: self._resolve_poison,
            ActionType.TREAT: self._resolve_treat,
            ActionType.WAIT: self._resolve_wait,
        }
        return handlers[intent.action_type](state, intent, round_number)

    def _resolve_move(self, state: GameState, intent: ActionIntent, round_number: int) -> EventRecord:
        actor = state.agents[intent.actor_id]
        origin = actor.location_id
        origin_witnesses = state.occupants(origin, include_dead=False)
        actor.location_id = intent.location_id or origin
        movement = {
            "from": origin,
            "to": actor.location_id,
            "round_number": round_number,
            "action_step": state.action_step + 1,
        }
        actor.location_state["previous_area"] = origin
        actor.location_state["current_area"] = actor.location_id
        actor.location_state.setdefault("movement_history", []).append(movement)
        witnesses = list(dict.fromkeys(
            origin_witnesses + state.occupants(actor.location_id, include_dead=False)
        ))
        event = self._event(
            round_number,
            "move",
            f"{actor.display_name} 从{state.locations[origin]['name']}前往{state.locations[actor.location_id]['name']}。",
            actors=[actor.agent_id],
            location_id=actor.location_id,
            public=False,
            witnesses=witnesses,
            state_changes=[{"agent_id": actor.agent_id, "location_id": actor.location_id}],
            payload={"origin_id": origin, "destination_id": actor.location_id},
        )
        return event

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
            taken = bool(item.portable and item.holder_id is None)
            if taken:
                item.transition(
                    "take",
                    round_number=round_number,
                    action_step=state.action_step,
                    actor_id=actor.agent_id,
                    holder_id=actor.agent_id,
                    location_id=None,
                    hidden=False,
                    witnesses=[actor.agent_id],
                    public=False,
                )
                if item.object_id not in actor.inventory:
                    actor.inventory.append(item.object_id)
                actor.inventory_state["held_items"] = list(actor.inventory)
            previous_searcher = self._record_search(state, actor.agent_id, location_id, round_number)
            remaining = sum(
                1 for candidate in state.objects.values()
                if candidate.location_id == location_id
                and actor.agent_id not in candidate.discovered_by
            )
            progress_hint = (
                "搜查尚未到底：此处仍有可疑角落没有核清。"
                if remaining
                else "就你目前能辨认的范围而言，此处暂时没有更多未见物证。"
            )
            clue_claim = str(
                item.metadata.get("clue_claim")
                or item.metadata.get("description")
                or f"{item.name}可能与当前案件有关。"
            )
            event = self._event(
                round_number,
                "discovery",
                (
                    f"{actor.display_name} 在{state.locations[location_id]['name']}发现并取得了{item.name}。"
                    if taken
                    else f"{actor.display_name} 在{state.locations[location_id]['name']}发现了{item.name}。"
                ),
                actors=[actor.agent_id],
                location_id=location_id,
                public=False,
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
                    "search_progress": progress_hint,
                    "evidence_remaining": bool(remaining),
                    "previous_searcher_id": previous_searcher,
                    "taken": taken,
                },
            )
            if taken and item.history:
                item.history[-1].event_id = event.event_id
            return event
        search_history = state.flags.get("location_search_history", {}).get(location_id, [])
        previous_entry = next(
            (entry for entry in reversed(search_history) if entry.get("agent_id") != actor.agent_id),
            None,
        )
        previous_id = str((previous_entry or {}).get("agent_id") or "")
        previous_name = state.agents[previous_id].display_name if previous_id in state.agents else "另一名住客"
        observations = list(state.locations[location_id].get("search_observations", []))
        observation_index = len(search_history) % len(observations) if observations else 0
        observation = (
            str(observations[observation_index]).format(previous_name=previous_name)
            if observations
            else f"器物的位置并非全然自然；{previous_name}留下的翻动痕迹尚未被雨气掩去。"
        )
        self._record_search(state, actor.agent_id, location_id, round_number)
        progress_hint = "没有找到新物品；现有痕迹表明这里暂时没有尚未辨认的物证。"
        return self._event(
            round_number,
            "investigation_empty",
            f"{actor.display_name} 搜查了{state.locations[location_id]['name']}，没有发现新物品，但注意到：{observation}",
            actors=[actor.agent_id],
            location_id=location_id,
            public=False,
            witnesses=state.occupants(location_id, include_dead=False),
            payload={
                "disturbance_trace": observation,
                "search_progress": progress_hint,
                "evidence_remaining": False,
                "previous_searcher_id": previous_id or None,
            },
        )

    @staticmethod
    def _record_search(
        state: GameState,
        actor_id: str,
        location_id: str,
        round_number: int,
    ) -> str | None:
        histories = state.flags.setdefault("location_search_history", {})
        history = histories.setdefault(location_id, [])
        previous = next(
            (entry for entry in reversed(history) if entry.get("agent_id") != actor_id),
            None,
        )
        history.append({
            "agent_id": actor_id,
            "round_number": round_number,
            "action_step": state.action_step + 1,
        })
        return str(previous.get("agent_id")) if previous else None

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
        displayed_item = None
        display_object_id = str(intent.metadata.get("display_object_id") or "")
        item_disposition = str(intent.metadata.get("item_disposition") or "none")
        if display_object_id:
            candidate = state.objects.get(display_object_id)
            if candidate and candidate.holder_id == actor.agent_id:
                displayed_item = candidate
                item_disposition = "show"
                viewers = state.occupants(actor.location_id, include_dead=False)
                displayed_item.discovered_by = list(dict.fromkeys([
                    *displayed_item.discovered_by, *viewers,
                ]))
                displayed_item.transition(
                    "display",
                    round_number=round_number,
                    action_step=state.action_step,
                    actor_id=actor.agent_id,
                    witnesses=viewers,
                    public=True,
                )
                actor.inventory_state.setdefault(
                    "publicly_revealed_items", []
                ).append(displayed_item.object_id)
        event = self._event(
            round_number,
            "conversation",
            f"{actor.display_name} 对{target.display_name}说：“{topic}”",
            actors=[actor.agent_id, target.agent_id],
            location_id=actor.location_id,
            public=False,
            witnesses=state.occupants(actor.location_id, include_dead=False),
            payload={
                "content": topic,
                "speaker_id": actor.agent_id,
                "listener_id": target.agent_id,
                "shared_belief_id": shared_belief.belief_id if shared_belief else None,
                "shared_claim": shared_belief.claim if shared_belief else None,
                "shared_truth_id": shared_belief.truth_id if shared_belief else None,
                "shared_confidence": shared_belief.confidence if shared_belief else None,
                "displayed_object_id": displayed_item.object_id if displayed_item else None,
                "displayed_object_name": displayed_item.name if displayed_item else None,
                "item_disposition": "show" if displayed_item else (
                    item_disposition if item_disposition == "refuse" else "none"
                ),
                "_host_item_disposition": item_disposition,
            },
        )
        if displayed_item and displayed_item.history:
            displayed_item.history[-1].event_id = event.event_id
        state.conversations.append(ConversationRecord(
            conversation_id=f"conversation-{event.event_id}",
            event_id=event.event_id,
            round_number=round_number,
            action_step=state.action_step,
            speaker_id=actor.agent_id,
            listener_id=target.agent_id,
            content=topic,
            location_id=actor.location_id,
            witnesses=list(event.witnesses),
            shared_information_id=shared_belief.belief_id if shared_belief else None,
            displayed_object_id=displayed_item.object_id if displayed_item else None,
        ))
        return event

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
        item.transition(
            "transfer",
            round_number=round_number,
            action_step=state.action_step,
            actor_id=actor.agent_id,
            counterparty_id=target.agent_id,
            holder_id=target.agent_id,
            location_id=None,
            hidden=False,
            witnesses=state.occupants(actor.location_id, include_dead=False),
            public=True,
        )
        actor.inventory.remove(item.object_id)
        target.inventory.append(item.object_id)
        actor.inventory_state["held_items"] = list(actor.inventory)
        target.inventory_state["held_items"] = list(target.inventory)
        actor.inventory_state.setdefault("exchanged_items", []).append(item.object_id)
        target.inventory_state.setdefault("exchanged_items", []).append(item.object_id)
        event = self._event(
            round_number,
            "object_transfer",
            f"{actor.display_name} 将{item.name}交给了{target.display_name}。",
            actors=[actor.agent_id, target.agent_id],
            location_id=actor.location_id,
            public=False,
            witnesses=state.occupants(actor.location_id, include_dead=False),
            state_changes=[{"object_id": item.object_id, "holder_id": target.agent_id}],
        )
        if item.history:
            item.history[-1].event_id = event.event_id
        return event

    def _resolve_poison(self, state: GameState, intent: ActionIntent, round_number: int) -> EventRecord:
        actor = state.agents[intent.actor_id]
        target = state.agents.get(intent.target_id or "")
        if target is None or target.location_id != actor.location_id or target.life_state == LifeState.DEAD:
            return self._failed_event(round_number, actor.agent_id, actor.display_name, "下毒", "目标不在场", actor.location_id)

        round_poisons = state.flags.setdefault("poisons_by_round", {}).setdefault(
            str(round_number), []
        )
        if actor.agent_id not in round_poisons:
            round_poisons.append(actor.agent_id)

        base_chance = float(intent.metadata.get("success_chance", 0.7))
        succeeded = self.random.random() <= max(0.0, min(1.0, base_chance))
        state.flags.setdefault("pending_poisons", []).append({
            "poisoner_id": actor.agent_id,
            "target_id": target.agent_id,
            "queued_round": round_number,
            "apply_round": round_number + 1,
            "succeeded": succeeded,
            "condition": str(intent.metadata.get("condition") or "中毒"),
            "ability_id": intent.metadata.get("ability_id"),
        })
        return self._event(
            round_number,
            "poison_queued",
            f"{actor.display_name}秘密对{target.display_name}实施了下毒。",
            actors=[actor.agent_id],
            location_id=actor.location_id,
            public=False,
            witnesses=[actor.agent_id],
            payload={
                "target_id": target.agent_id,
                "apply_round": round_number + 1,
                "succeeded": succeeded,
                "ability_id": intent.metadata.get("ability_id"),
                "ability_label": intent.metadata.get("ability_label"),
            },
        )

    def _resolve_pending_poisons(
        self,
        state: GameState,
        round_number: int,
        action_step: int,
    ) -> list[EventRecord]:
        pending = list(state.flags.get("pending_poisons", []))
        remaining: list[dict[str, Any]] = []
        events: list[EventRecord] = []
        for dose in pending:
            if int(dose.get("apply_round", round_number + 1)) > round_number:
                remaining.append(dose)
                continue
            target = state.agents.get(str(dose.get("target_id") or ""))
            if target is None or target.life_state == LifeState.DEAD:
                continue
            if not bool(dose.get("succeeded")):
                continue
            before_state = target.life_state
            target.life_state = (
                LifeState.DEAD
                if before_state == LifeState.INJURED
                else LifeState.INJURED
            )
            condition = str(dose.get("condition") or "中毒")
            if condition not in target.conditions:
                target.conditions.append(condition)
            witnesses = state.occupants(target.location_id, include_dead=True)
            dropped_items: list[str] = []
            if target.life_state == LifeState.DEAD:
                for object_id in list(target.inventory):
                    item = state.objects.get(object_id)
                    if item is None:
                        continue
                    item.transition(
                        "drop",
                        round_number=round_number,
                        action_step=action_step,
                        actor_id=target.agent_id,
                        holder_id=None,
                        location_id=target.location_id,
                        hidden=False,
                        witnesses=witnesses,
                        public=True,
                    )
                    item.discovered_by = list(dict.fromkeys([
                        *item.discovered_by, *witnesses,
                    ]))
                    dropped_items.append(object_id)
                target.inventory.clear()
                target.inventory_state["held_items"] = []
            event = self._event(
                round_number,
                "poison_effect",
                f"{target.display_name}突然毒发，当前状态为{target.life_state.value}。",
                actors=[target.agent_id],
                location_id=target.location_id,
                public=False,
                witnesses=witnesses,
                state_changes=[{
                    "agent_id": target.agent_id,
                    "life_state": target.life_state.value,
                }],
                payload={
                    "previous_life_state": before_state.value,
                    "condition": condition,
                    "dropped_object_ids": dropped_items,
                },
            )
            event.action_step = action_step
            events.append(event)
        state.flags["pending_poisons"] = remaining
        return events

    def _resolve_treat(self, state: GameState, intent: ActionIntent, round_number: int) -> EventRecord:
        actor = state.agents[intent.actor_id]
        target = state.agents.get(intent.target_id or actor.agent_id)
        if target is None or target.location_id != actor.location_id or target.life_state == LifeState.DEAD:
            return self._failed_event(round_number, actor.agent_id, actor.display_name, "治疗", "目标不在场或已经死亡", actor.location_id)
        before_state = target.life_state
        target.life_state = LifeState.ALIVE
        target.conditions = []
        return self._event(
            round_number,
            "treatment",
            f"{actor.display_name} 为{target.display_name}进行了治疗。",
            actors=[actor.agent_id, target.agent_id],
            location_id=actor.location_id,
            public=False,
            witnesses=state.occupants(actor.location_id, include_dead=False),
            state_changes=[{
                "agent_id": target.agent_id,
                "life_state": target.life_state.value,
            }],
            payload={
                "previous_life_state": before_state.value,
                "ability_id": intent.metadata.get("ability_id"),
                "ability_label": intent.metadata.get("ability_label"),
            },
        )

    def _resolve_wait(self, state: GameState, intent: ActionIntent, round_number: int) -> EventRecord:
        actor = state.agents[intent.actor_id]
        return self._event(
            round_number,
            "wait",
            f"{actor.display_name} 留在{state.locations[actor.location_id]['name']}观察局势。",
            actors=[actor.agent_id],
            location_id=actor.location_id,
            public=False,
            witnesses=state.occupants(actor.location_id, include_dead=False),
        )

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
            public=False,
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
