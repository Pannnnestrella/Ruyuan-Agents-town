import tempfile
import unittest

from modules.interactive import ActionIntent, ActionType, GameService
from modules.interactive.information import (
    neutral_belief_claim,
    render_belief_claim,
)
from modules.interactive.models import Belief


class InformationPerspectiveTests(unittest.TestCase):
    def test_structured_owner_perspective_renders_first_and_third_person(self):
        belief = Belief(
            belief_id="belief-fu-test",
            claim="异常军饷确实由你调拨，但你必须解释账目。",
            source="个人经历",
            perspective_owner_id="傅融",
        )

        self.assertEqual(
            render_belief_claim(
                belief, speaker_id="傅融", owner_name="傅融",
            ),
            "异常军饷确实由我调拨，但我必须解释账目。",
        )
        self.assertEqual(
            neutral_belief_claim(belief, owner_name="傅融"),
            "异常军饷确实由傅融调拨，但傅融必须解释账目。",
        )

    def test_shared_self_memory_is_spoken_as_me_and_stored_by_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = GameService(".", results_root=temp_dir).create_game(
                "stormbound_inn",
                game_id="perspective-test",
                seed=0,
                player_agent_id="广陵王",
            )
            speaker = session.state.agents["傅融"]
            listener = session.state.agents["广陵王"]
            speaker.location_id = listener.location_id = "lobby"
            belief = next(
                item for item in speaker.beliefs
                if "异常军饷确实由你调拨" in item.claim
            )
            self.assertEqual(belief.perspective_owner_id, "傅融")

            result = session.engine.resolve_free_action(
                session.state,
                ActionIntent(
                    actor_id="傅融",
                    action_type=ActionType.TALK,
                    target_id="广陵王",
                    content="",
                    metadata={"share_belief_id": belief.belief_id},
                ),
            )
            event = result.events[0]
            self.assertIn("由我调拨", event.payload["content"])
            self.assertNotIn("由你调拨", event.payload["content"])
            self.assertIn("由傅融调拨", event.payload["shared_claim"])

            session._update_beliefs_from_round_events(result.events)
            received = next(
                item for item in listener.beliefs
                if item.source == event.event_id
            )
            self.assertIn("由傅融调拨", received.claim)
            self.assertNotIn("由你调拨", received.claim)


if __name__ == "__main__":
    unittest.main()
