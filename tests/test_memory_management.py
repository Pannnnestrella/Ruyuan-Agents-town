"""Tests for importance-aware belief selection, dedup upgrade, consolidation."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from modules.interactive import GameSession, ScenarioLoader
from modules.interactive.belief_select import select_context_beliefs
from modules.interactive.models import Belief, EventRecord

ROOT = Path(__file__).resolve().parents[1]


class BeliefSelectionTests(unittest.TestCase):
    def test_early_key_evidence_survives_a_long_game(self):
        key = Belief(
            belief_id="key-evidence",
            claim="死者颈后有针孔,与淬毒细针吻合",
            source="event-1",
            confidence=1.0,
            information_type="fact",
            source_type="observation",
            truth_id="truth-needle",
            learned_round=0,
        )
        fillers = [
            Belief(
                belief_id=f"chatter-{index}",
                claim=f"闲谈内容第{index}条",
                source=f"event-chatter-{index}",
                confidence=0.5,
                information_type="testimony",
                source_type="direct_statement",
                learned_round=index // 8,
            )
            for index in range(40)
        ]
        beliefs = [key, *fillers]
        selected = select_context_beliefs(beliefs, current_round=5, limit=32)

        self.assertEqual(len(selected), 32)
        self.assertIn("key-evidence", {belief.belief_id for belief in selected})
        # A recency-only slice would have evicted it.
        self.assertNotIn(
            "key-evidence", {belief.belief_id for belief in beliefs[-32:]},
        )
        positions = [beliefs.index(belief) for belief in selected]
        self.assertEqual(positions, sorted(positions), "必须保持时间顺序")

    def test_small_lists_pass_through_unchanged(self):
        beliefs = [
            Belief(belief_id=f"b{i}", claim=f"c{i}", source=f"s{i}")
            for i in range(5)
        ]
        self.assertEqual(
            select_context_beliefs(beliefs, current_round=1, limit=32), beliefs,
        )


class BeliefWritebackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        loaded = ScenarioLoader(ROOT).load("stormbound_inn")
        state = loaded.create_game_state("memory-test", seed=5)
        self.session = GameSession(
            loaded, state, results_root=self.tmp.name, seed=5, planner=None,
        )
        self.state = self.session.state
        self.agent_a, self.agent_b = sorted(self.state.agents)[:2]

    def tearDown(self):
        self.tmp.cleanup()

    def _count_claim(self, agent_id: str, fragment: str) -> list[Belief]:
        return [
            belief for belief in self.state.agents[agent_id].beliefs
            if fragment in belief.claim
        ]

    def test_direct_observation_upgrades_hearsay_instead_of_duplicating(self):
        claim = "针孔位于死者颈后三寸处"
        heard = EventRecord(
            event_id="event-heard",
            round_number=1,
            event_type="conversation",
            summary="交谈",
            actors=[self.agent_b, self.agent_a],
            location_id="lobby",
            witnesses=[self.agent_a, self.agent_b],
            payload={
                "speaker_id": self.agent_b,
                "listener_id": self.agent_a,
                "content": claim,
                "shared_claim": claim,
                "shared_confidence": 0.65,
            },
        )
        seen = EventRecord(
            event_id="event-seen",
            round_number=2,
            event_type="discovery",
            summary="发现针孔",
            actors=[self.agent_a],
            location_id="guest_room",
            witnesses=[self.agent_a],
            payload={"clue_claim": claim, "truth_id": "truth-needle"},
        )
        self.session._update_beliefs_from_round_events([heard])
        self.session._update_beliefs_from_round_events([seen])

        matches = self._count_claim(self.agent_a, claim)
        self.assertEqual(len(matches), 1, "同一主张不应堆成两条信念")
        self.assertEqual(matches[0].confidence, 1.0)
        self.assertEqual(matches[0].stance, "observed")
        self.assertEqual(matches[0].truth_id, "truth-needle")

    def test_identical_observations_are_not_stacked(self):
        events = [
            EventRecord(
                event_id=f"event-wait-{index}",
                round_number=index,
                event_type="wait",
                summary="孙策在原地观察大堂动静",
                actors=["孙策"],
                location_id="lobby",
                witnesses=[self.agent_a],
            )
            for index in range(2)
        ]
        self.session._update_beliefs_from_round_events(events)
        self.assertEqual(len(self._count_claim(self.agent_a, "原地观察")), 1)

    def test_consolidation_links_corroborating_beliefs(self):
        agent = self.state.agents[self.agent_a]
        first = Belief(
            belief_id="corr-1",
            claim="账册第三页被撕去",
            source="event-x",
            truth_id="truth-ledger",
            information_type="testimony",
        )
        second = Belief(
            belief_id="corr-2",
            claim="有人看见账册缺了一页",
            source="event-y",
            truth_id="truth-ledger",
            information_type="testimony",
        )
        lonely = Belief(
            belief_id="lonely-1",
            claim="据说后院有陌生脚印",
            source="event-z",
            information_type="testimony",
        )
        agent.beliefs.extend([first, second, lonely])
        self.session._update_beliefs_from_round_events([])

        self.assertIn("corr-2", first.supporting_ids)
        self.assertIn("corr-1", second.supporting_ids)
        self.assertFalse(first.verification_questions)
        self.assertTrue(lonely.verification_questions)


if __name__ == "__main__":
    unittest.main()
