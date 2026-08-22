"""Read-only public, observer, and director state projections."""

from __future__ import annotations

from typing import Any

from ..domain.models import GamePhase


class StateProjectionService:
    """Build API views without owning or mutating the game session."""

    def __init__(self, session: Any):
        self.session = session

    def public_state(self) -> dict[str, Any]:
        state = self.session.state
        data = state.public_view()
        data["title"] = self.session.loaded.scenario["title"]
        data["premise"] = self.session.loaded.scenario["premise"]
        data["planner"] = self.session.planner.__class__.__name__
        data["planner_provider"] = getattr(self.session.planner, "provider_name", "heuristic")
        recent_model_calls = [
            item for item in state.model_usage
            if item.get("stage") in {"action", "round_discussion"}
        ][-24:]
        fallback_calls = [
            item for item in recent_model_calls
            if item.get("actual_source") == "heuristic_fallback"
        ]
        data["planner_runtime"] = {
            "recent_calls": len(recent_model_calls),
            "fallback_calls": len(fallback_calls),
            "llm_calls": sum(item.get("actual_source") == "llm" for item in recent_model_calls),
            "is_falling_back": bool(
                recent_model_calls and len(fallback_calls) == len(recent_model_calls)
            ),
        }
        data["public_facts"] = self.session.loaded.scenario.get("public_facts", [])
        data["ending_questions"] = self.session.loaded.scenario.get("ending_questions", [])
        data["game_rules"] = self.session.loaded.scenario.get("game_rules", [])
        data["controlled_agent_id"] = state.player_agent_id
        if state.phase == GamePhase.FINISHED:
            data["voting_result"] = dict(state.flags.get("voting_result", {}))
            data["scoreboard"] = self.session.scoreboard()
        return data

    def observer_state(self) -> dict[str, Any]:
        data = self.public_state()
        data["events"] = [
            event.to_dict()
            for event in self.session.state.events
            if event.event_type != "poison_queued"
            and not (
                event.event_type == "action_failed"
                and event.payload.get("action") == "下毒"
            )
        ]
        return data

    def director_state(self) -> dict[str, Any]:
        # The large casebook builder remains a private compatibility seam while
        # all endpoint-facing projection ownership lives behind this service.
        return self.session._build_director_state()
