"""Tests for the spoken-promise (commitment) protocol."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from modules.interactive import GameSession, LLMIntentPlanner, ScenarioLoader
from modules.interactive.models import ActionType, EventRecord

ROOT = Path(__file__).resolve().parents[1]


class CommitmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        loaded = ScenarioLoader(ROOT).load("stormbound_inn")
        state = loaded.create_game_state("commitment-test", seed=6)
        self.session = GameSession(
            loaded, state, results_root=self.tmp.name, seed=6, planner=None,
        )
        self.state = self.session.state
        self.promisor, self.promisee = sorted(self.state.agents)[:2]
        self.object_id = next(iter(self.state.objects))
        item = self.state.objects[self.object_id]
        item.holder_id = self.promisor
        item.location_id = None
        self.state.agents[self.promisor].inventory.append(self.object_id)

    def tearDown(self):
        self.tmp.cleanup()

    def _promise_event(self, *, object_id: str | None) -> EventRecord:
        promise: dict = {"content": "下一轮我把这件东西交给你"}
        if object_id:
            promise["object_id"] = object_id
        return EventRecord(
            event_id=f"event-promise-{object_id or 'talk'}",
            round_number=self.state.round_number,
            event_type="conversation",
            summary="交谈",
            actors=[self.promisor, self.promisee],
            witnesses=[self.promisor, self.promisee],
            payload={
                "speaker_id": self.promisor,
                "listener_id": self.promisee,
                "content": "我保证明轮交给你。",
                "promise": promise,
            },
        )

    def _entries(self):
        return self.state.flags.get("commitments", [])

    def test_object_promise_is_recorded_and_fulfilled_by_transfer(self):
        self.session._process_commitments([
            self._promise_event(object_id=self.object_id),
        ])
        self.assertEqual(len(self._entries()), 1)
        self.assertEqual(self._entries()[0]["status"], "open")

        transfer = EventRecord(
            event_id="event-transfer-1",
            round_number=self.state.round_number,
            event_type="object_transfer",
            summary="交付",
            actors=[self.promisor, self.promisee],
            witnesses=[self.promisor, self.promisee],
            state_changes=[{
                "object_id": self.object_id,
                "holder_id": self.promisee,
            }],
        )
        self.session._process_commitments([transfer])
        self.assertEqual(self._entries()[0]["status"], "fulfilled")
        fulfilled_beliefs = [
            belief for belief in self.state.agents[self.promisee].beliefs
            if "兑现了" in belief.claim
        ]
        self.assertTrue(fulfilled_beliefs)

    def test_object_promise_breaks_after_the_deadline(self):
        self.session._process_commitments([
            self._promise_event(object_id=self.object_id),
        ])
        self.state.round_number = self._entries()[0]["due_round"] + 1
        self.session._process_commitments([])
        self.assertEqual(self._entries()[0]["status"], "broken")
        broken_beliefs = [
            belief for belief in self.state.agents[self.promisee].beliefs
            if "未在约定时限内兑现" in belief.claim
        ]
        self.assertTrue(broken_beliefs)

    def test_promise_about_unheld_object_becomes_free_form_and_lapses(self):
        self.state.agents[self.promisor].inventory.remove(self.object_id)
        self.state.objects[self.object_id].holder_id = self.promisee
        self.session._process_commitments([
            self._promise_event(object_id=self.object_id),
        ])
        entry = self._entries()[0]
        self.assertIsNone(entry["object_id"])
        self.state.round_number = entry["due_round"] + 1
        self.session._process_commitments([])
        self.assertEqual(self._entries()[0]["status"], "lapsed")
        self.assertFalse([
            belief for belief in self.state.agents[self.promisee].beliefs
            if "未在约定时限内兑现" in belief.claim
        ])

    def test_parse_intent_sanitizes_promise_field(self):
        intent = LLMIntentPlanner._parse_intent("甲", (
            '{"action_type": "talk", "target_id": "乙", "content": "台词",'
            ' "promise": {"content": "  明轮交出账册  ", "object_id": "ledger"}}'
        ))
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action_type, ActionType.TALK)
        self.assertEqual(
            intent.metadata["promise"],
            {"content": "明轮交出账册", "object_id": "ledger"},
        )
        no_promise = LLMIntentPlanner._parse_intent("甲", (
            '{"action_type": "talk", "target_id": "乙", "promise": {"content": ""}}'
        ))
        self.assertNotIn("promise", no_promise.metadata)


if __name__ == "__main__":
    unittest.main()
