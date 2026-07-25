"""Tests for engine-side rule convergence and bulletin location config."""

from __future__ import annotations

import unittest
from pathlib import Path

from modules.interactive import LLMIntentPlanner, RoundEngine, ScenarioLoader
from modules.interactive.models import ActionIntent, ActionType
from modules.interactive.round_engine import bulletin_location

ROOT = Path(__file__).resolve().parents[1]


class RuleConvergenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loaded = ScenarioLoader(ROOT).load("stormbound_inn")

    def setUp(self):
        self.state = self.loaded.create_game_state("rules-test", seed=1)
        self.engine = RoundEngine(seed=1)

    def test_bulletin_location_comes_from_state_flags(self):
        self.assertEqual(self.state.flags["bulletin_location_id"], "lobby")
        self.assertEqual(bulletin_location(self.state), "lobby")
        self.state.flags["bulletin_location_id"] = "tea_room"
        self.assertEqual(bulletin_location(self.state), "tea_room")

    def test_post_notice_follows_configured_bulletin_location(self):
        actor_id = sorted(self.state.agents)[0]
        actor = self.state.agents[actor_id]
        actor.location_id = "lobby"
        intent = ActionIntent(
            actor_id=actor_id,
            action_type=ActionType.POST_NOTICE,
            content="登记簿的墨迹有先后之分。",
        )
        self.assertIsNone(self.engine.validate_intent(self.state, intent))
        self.state.flags["bulletin_location_id"] = "kitchen"
        self.assertIsNotNone(self.engine.validate_intent(self.state, intent))

    def test_planner_grounding_delegates_to_engine_rules(self):
        actor_id = sorted(self.state.agents)[0]
        actor = self.state.agents[actor_id]
        connections = self.state.locations[actor.location_id].get("connections", [])
        self.assertTrue(connections)
        valid_move = ActionIntent(
            actor_id=actor_id,
            action_type=ActionType.MOVE,
            location_id=connections[0],
        )
        invalid_move = ActionIntent(
            actor_id=actor_id,
            action_type=ActionType.MOVE,
            location_id="不存在的地方",
        )
        self.assertTrue(
            LLMIntentPlanner._intent_is_grounded(self.state, valid_move),
        )
        self.assertFalse(
            LLMIntentPlanner._intent_is_grounded(self.state, invalid_move),
        )


if __name__ == "__main__":
    unittest.main()
