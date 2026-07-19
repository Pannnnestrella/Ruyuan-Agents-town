"""Resolve authored delayed world consequences at round boundaries."""

from __future__ import annotations

from typing import Any, Iterable

from .models import EventRecord, GameState


class TriggerResolver:
    def __init__(self, triggers: Iterable[dict[str, Any]]):
        self.triggers = list(triggers)
        self._event_sequence = 0

    def apply_due(self, state: GameState) -> list[EventRecord]:
        upcoming_round = min(state.round_number + 1, state.max_rounds)
        events: list[EventRecord] = []
        for trigger in self.triggers:
            marker = f"trigger_used:{trigger['id']}"
            if state.flags.get(marker):
                continue
            if not self._conditions_match(state, trigger.get("conditions", {}), upcoming_round):
                continue
            for effect in trigger.get("effects", []):
                event = self._apply_effect(state, trigger, effect, upcoming_round)
                if event is not None:
                    events.append(event)
            state.flags[marker] = True
        state.events.extend(events)
        return events

    @staticmethod
    def _conditions_match(
        state: GameState,
        conditions: dict[str, Any],
        upcoming_round: int,
    ) -> bool:
        if upcoming_round < int(conditions.get("min_round", 0)):
            return False
        due_flag = conditions.get("flag_round_due")
        if due_flag and state.flags.get(due_flag) != upcoming_round:
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
        return True

    def _apply_effect(
        self,
        state: GameState,
        trigger: dict[str, Any],
        effect: dict[str, Any],
        round_number: int,
    ) -> EventRecord | None:
        effect_type = effect.get("type")
        if effect_type == "set_flag":
            state.flags[effect["flag"]] = effect.get("value")
            return None
        if effect_type == "public_fact":
            return self._event(
                round_number,
                "world_trigger",
                effect["claim"],
                public=True,
                location_id=effect.get("location_id"),
                payload={"trigger_id": trigger["id"]},
            )
        if effect_type == "remove_object":
            item = state.objects[effect["object_id"]]
            item.location_id = None
            item.holder_id = None
            item.hidden = True
            item.metadata["removed_round"] = round_number
            item.metadata["removed_reason"] = effect.get("reason", "world_trigger")
            return self._event(
                round_number,
                "evidence_lost",
                effect["summary"],
                public=bool(effect.get("public", False)),
                location_id=effect.get("location_id"),
                payload={"trigger_id": trigger["id"], "object_id": item.object_id},
            )
        raise ValueError(f"Unsupported world-trigger effect: {effect_type}")

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
            event_id=f"trigger-event-{round_number:02d}-{self._event_sequence:04d}",
            round_number=round_number,
            event_type=event_type,
            summary=summary,
            location_id=location_id,
            public=public,
            payload=payload or {},
        )
