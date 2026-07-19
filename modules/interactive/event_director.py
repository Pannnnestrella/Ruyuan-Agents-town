"""State-aware event-card suggestions and effect application."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any, Iterable

from .models import EventCard, EventRecord, GamePhase, GameState, LifeState


class EventDirector:
    CATEGORIES = ("pressure", "information", "relationship")

    def __init__(self, cards: Iterable[dict[str, Any]], *, seed: int = 0):
        self.cards = {
            card["id"]: EventCard(
                card_id=card["id"],
                title=card["title"],
                category=card["category"],
                description=card["description"],
                impact_preview=card["impact_preview"],
                effects=list(card.get("effects", [])),
                preconditions=dict(card.get("preconditions", {})),
                once=bool(card.get("once", True)),
                hidden_consequence=card.get("hidden_consequence", ""),
            )
            for card in cards
        }
        self.random = random.Random(seed)
        self._event_sequence = 0

    def suggest(self, state: GameState) -> list[EventCard]:
        """Return at most one legal card per category."""
        eligible: dict[str, list[EventCard]] = defaultdict(list)
        for card in self.cards.values():
            if card.card_id not in state.seen_event_cards and self.is_eligible(state, card):
                eligible[card.category].append(card)

        suggestions: list[EventCard] = []
        for category in self.CATEGORIES:
            candidates = sorted(eligible.get(category, []), key=lambda item: item.card_id)
            if not candidates:
                fallback = self._fallback_card(state, category)
                self.cards[fallback.card_id] = fallback
                candidates = [fallback]
            suggestions.append(self.random.choice(candidates))
        return suggestions

    def quiet_card(self, state: GameState) -> EventCard:
        """Return the explicit no-intervention option for the upcoming round."""
        upcoming_round = min(state.round_number + 1, state.max_rounds)
        card_id = f"quiet-{upcoming_round:02d}"
        card = EventCard(
            card_id=card_id,
            title="静观其变",
            category="quiet",
            description="本轮不向客栈施加额外局势，让六名角色只按各自目标与记忆行动。",
            impact_preview="没有外部事件；人物仍会移动、调查、交谈、隐瞒或尝试逃脱。",
            effects=[],
            preconditions={"min_round": upcoming_round},
            once=True,
            hidden_consequence="空事件不会改变客观真相或世界标记。",
        )
        self.cards[card_id] = card
        return card

    def is_eligible(self, state: GameState, card: EventCard) -> bool:
        if card.once and card.card_id in state.used_event_cards:
            return False
        conditions = card.preconditions
        # Cards are selected between rounds and apply to the upcoming round.
        upcoming_round = min(state.round_number + 1, state.max_rounds)
        if upcoming_round < int(conditions.get("min_round", 0)):
            return False
        absent_flag = conditions.get("flag_absent")
        if absent_flag and state.flags.get(absent_flag) is not None:
            return False
        for key, expected in conditions.get("flag_equals", {}).items():
            if state.flags.get(key) != expected:
                return False
        object_id = conditions.get("object_undiscovered")
        if object_id:
            item = state.objects.get(object_id)
            if item is None or item.discovered_by:
                return False
        required_alive = conditions.get("agent_alive")
        if required_alive:
            agent = state.agents.get(required_alive)
            if agent is None or not agent.can_act:
                return False
        return True

    def apply(self, state: GameState, card_id: str) -> list[EventRecord]:
        if state.phase not in {
            GamePhase.INTERVENTION,
            GamePhase.ROUND_COMPLETE,
        }:
            raise ValueError(f"Cannot select an event card during {state.phase.value}")
        card = self.cards.get(card_id)
        if card is None:
            raise KeyError(f"Unknown event card: {card_id}")
        if not self.is_eligible(state, card):
            raise ValueError(f"Event card is not eligible: {card_id}")

        state.active_event_card = card.card_id
        if card.once:
            state.used_event_cards.append(card.card_id)
        event_round = min(state.round_number + 1, state.max_rounds)
        events: list[EventRecord] = [
            self._event(
                event_round,
                "event_card_selected",
                f"局势事件“{card.title}”被选中：{card.description}",
                public=True,
                payload={
                    "card_id": card.card_id,
                    "category": card.category,
                    "title": card.title,
                    "description": card.description,
                    "impact_preview": card.impact_preview,
                },
            )
        ]

        for effect in card.effects:
            effect_type = effect.get("type")
            if effect_type == "set_flag":
                state.flags[effect["flag"]] = effect.get("value")
            elif effect_type == "set_deadline":
                state.flags[effect["flag"]] = state.round_number + int(effect["rounds_from_now"])
            elif effect_type == "public_fact":
                events.append(
                    self._event(
                        event_round,
                        "public_fact",
                        effect["claim"],
                        public=True,
                        location_id=effect.get("location_id"),
                        payload={"source_card_id": card.card_id},
                    )
                )
            elif effect_type == "reveal_object_hint":
                item = state.objects[effect["object_id"]]
                location = state.locations[effect["location_id"]]["name"]
                events.append(
                    self._event(
                        event_round,
                        "object_hint",
                        f"有人注意到{location}可能藏着与{item.name}有关的痕迹。",
                        public=True,
                        location_id=effect["location_id"],
                        payload={"object_id": item.object_id, "source_card_id": card.card_id},
                    )
                )
            elif effect_type == "set_health_state":
                agent = state.agents[effect["agent_id"]]
                if agent.life_state != LifeState.DEAD:
                    target_state = LifeState(str(effect.get("life_state", "injured")))
                    agent.life_state = target_state
                    agent.health = {
                        LifeState.ALIVE: 100,
                        LifeState.INJURED: 65,
                        LifeState.SEVERELY_INJURED: 30,
                        LifeState.DEAD: 0,
                    }.get(target_state, 30)
                    health_event = self._event(
                        event_round,
                        "health_changed",
                        str(effect.get("summary") or f"{agent.display_name}当前状态变为{target_state.value}。"),
                        public=True,
                        location_id=agent.location_id,
                        payload={
                            "agent_id": agent.agent_id,
                            "life_state": target_state.value,
                            "source_card_id": card.card_id,
                        },
                    )
                    health_event.actors = [agent.agent_id]
                    health_event.witnesses = state.occupants(agent.location_id, include_dead=False)
                    events.append(health_event)
            elif effect_type == "drop_random_carried_item":
                candidates = [
                    (holder, state.objects[object_id])
                    for holder in state.agents.values()
                    if holder.life_state != LifeState.DEAD
                    for object_id in holder.inventory
                    if object_id in state.objects and state.objects[object_id].portable
                ]
                if candidates:
                    holder, item = self.random.choice(sorted(
                        candidates, key=lambda pair: (pair[0].agent_id, pair[1].object_id)
                    ))
                    holder.inventory.remove(item.object_id)
                    item.holder_id = None
                    item.location_id = holder.location_id
                    item.hidden = False
                    witnesses = state.occupants(holder.location_id, include_dead=False)
                    item.discovered_by = list(dict.fromkeys([*item.discovered_by, *witnesses]))
                    drop_event = self._event(
                        event_round,
                        "object_dropped",
                        f"一阵突如其来的碰撞中，{holder.display_name}随身的{item.name}掉落在{state.locations[holder.location_id]['name']}。",
                        public=True,
                        location_id=holder.location_id,
                        payload={
                            "object_id": item.object_id,
                            "holder_id": holder.agent_id,
                            "source_card_id": card.card_id,
                        },
                    )
                    drop_event.actors = [holder.agent_id]
                    drop_event.witnesses = witnesses
                    events.append(drop_event)
            else:
                raise ValueError(f"Unsupported event-card effect: {effect_type}")

        state.events.extend(events)
        state.phase = GamePhase.READY
        return events

    def _fallback_card(self, state: GameState, category: str) -> EventCard:
        upcoming_round = min(state.round_number + 1, state.max_rounds)
        card_id = f"director-{category}-{upcoming_round:02d}"
        if card_id in self.cards:
            return self.cards[card_id]

        if category == "pressure":
            return EventCard(
                card_id=card_id,
                title="风雨催更",
                category=category,
                description=f"第{upcoming_round}轮开始前，暴雨与雷声再次加剧，客栈中的人意识到留给自己的时间正在减少。",
                impact_preview="提高本轮紧迫感，但不改变既定真相。",
                effects=[{
                    "type": "public_fact",
                    "claim": f"第{upcoming_round}轮开始时风雨加剧，众人感到局势愈发紧迫。",
                }],
                preconditions={"min_round": upcoming_round},
                hidden_consequence="导演保底压力事件，用于避免静态卡牌耗尽。",
            )

        if category == "information":
            hidden_items = sorted(
                (
                    item for item in state.objects.values()
                    if item.hidden and not item.discovered_by and item.location_id
                ),
                key=lambda item: item.object_id,
            )
            if hidden_items:
                item = hidden_items[(upcoming_round - 1) % len(hidden_items)]
                location_id = item.location_id or "lobby"
                return EventCard(
                    card_id=card_id,
                    title="未尽的搜查",
                    category=category,
                    description=f"掌柜注意到{state.locations[location_id]['name']}仍有一处没有被彻底检查。",
                    impact_preview="公开一个值得调查的地点，但不直接揭示其中物品。",
                    effects=[{
                        "type": "reveal_object_hint",
                        "object_id": item.object_id,
                        "location_id": location_id,
                    }],
                    preconditions={"min_round": upcoming_round},
                    hidden_consequence=f"该地点实际关联物品：{item.name}。",
                )
            return EventCard(
                card_id=card_id,
                title="重新核对证词",
                category=category,
                description="掌柜请所有人重新核对已经公开的时间与地点，寻找彼此陈述中的矛盾。",
                impact_preview="促使角色回顾已知事实，不新增客观真相。",
                effects=[{
                    "type": "public_fact",
                    "claim": "掌柜要求众人重新核对已经公开的证词与时间。",
                }],
                preconditions={"min_round": upcoming_round},
                hidden_consequence="导演保底信息事件。",
            )

        living = sorted(
            (agent for agent in state.agents.values() if agent.can_act),
            key=lambda agent: agent.agent_id,
        )
        first = living[(upcoming_round - 1) % len(living)] if living else None
        second = living[upcoming_round % len(living)] if len(living) > 1 else first
        pair_text = (
            f"{first.display_name}与{second.display_name}"
            if first and second and first.agent_id != second.agent_id
            else "仍能行动的住客"
        )
        return EventCard(
            card_id=card_id,
            title="当面对质",
            category=category,
            description=f"掌柜提议让{pair_text}当众说明自己上一轮的行动理由。",
            impact_preview="制造一次公开交流机会，角色仍可选择坦白、回避或误导。",
            effects=[{
                "type": "public_fact",
                "claim": f"掌柜请{pair_text}当众说明上一轮的行动理由。",
            }],
            preconditions={"min_round": upcoming_round},
            hidden_consequence="导演保底关系事件，不强制角色说出私密事实。",
        )

    def _event(
        self,
        round_number: int,
        event_type: str,
        summary: str,
        *,
        public: bool,
        location_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> EventRecord:
        self._event_sequence += 1
        return EventRecord(
            event_id=f"card-event-{round_number:02d}-{self._event_sequence:04d}",
            round_number=round_number,
            event_type=event_type,
            summary=summary,
            location_id=location_id,
            public=public,
            payload=payload or {},
        )
