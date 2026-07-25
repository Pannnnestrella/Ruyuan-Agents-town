"""Tests for the plan-execution feedback loop (plan vs actual outcome)."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from modules.interactive import GameSession, ScenarioLoader
from modules.interactive.models import ActionIntent, ActionType, EventRecord

ROOT = Path(__file__).resolve().parents[1]


class PlanClosureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        loaded = ScenarioLoader(ROOT).load("stormbound_inn")
        state = loaded.create_game_state("plan-loop-test", seed=2)
        self.session = GameSession(
            loaded, state, results_root=self.tmp.name, seed=2, planner=None,
        )
        self.state = self.session.state
        self.actor_id = sorted(self.state.agents)[0]
        self.agent = self.state.agents[self.actor_id]

    def tearDown(self):
        self.tmp.cleanup()

    def _intent(self, action_type: ActionType) -> ActionIntent:
        intent = ActionIntent(actor_id=self.actor_id, action_type=action_type)
        intent.metadata["strategic_plan"] = {
            "objective": "查明死者身份",
            "steps": ["下一步继续追查"],
        }
        return intent

    def _event(self, event_type: str) -> EventRecord:
        return EventRecord(
            event_id=f"event-{event_type}",
            round_number=1,
            event_type=event_type,
            summary="测试事件",
            actors=[self.actor_id],
            location_id=self.agent.location_id,
        )

    def test_followed_plan_step_is_marked_executed(self):
        self.agent.strategic_plan = {"steps": ["先调查大堂的可疑物品"]}
        self.session._commit_strategic_plans(
            [self._intent(ActionType.INVESTIGATE)], [self._event("discovery")],
        )
        entry = self.agent.plan_history[-1]
        self.assertEqual(entry["execution_status"], "executed")
        self.assertEqual(entry["plan_adherence"], "followed")
        self.assertEqual(entry["planned_step"], "先调查大堂的可疑物品")

    def test_failed_action_is_marked_failed(self):
        self.agent.strategic_plan = {"steps": ["先调查大堂的可疑物品"]}
        self.session._commit_strategic_plans(
            [self._intent(ActionType.INVESTIGATE)], [self._event("action_failed")],
        )
        self.assertEqual(
            self.agent.plan_history[-1]["execution_status"], "failed",
        )

    def test_action_off_plan_is_flagged_as_possible_deviation(self):
        self.agent.strategic_plan = {"steps": ["先调查大堂的可疑物品"]}
        self.session._commit_strategic_plans(
            [self._intent(ActionType.WAIT)], [self._event("wait")],
        )
        self.assertEqual(
            self.agent.plan_history[-1]["plan_adherence"], "possibly_deviated",
        )

    def test_missing_prior_plan_yields_unknown_adherence(self):
        self.agent.strategic_plan = {}
        self.session._commit_strategic_plans(
            [self._intent(ActionType.WAIT)], [self._event("wait")],
        )
        entry = self.agent.plan_history[-1]
        self.assertEqual(entry["plan_adherence"], "unknown")
        self.assertEqual(entry["planned_step"], "")

    def test_intent_without_world_event_is_no_effect(self):
        self.agent.strategic_plan = {"steps": ["观察局势"]}
        self.session._commit_strategic_plans(
            [self._intent(ActionType.WAIT)], [],
        )
        self.assertEqual(
            self.agent.plan_history[-1]["execution_status"], "no_effect",
        )


if __name__ == "__main__":
    unittest.main()
