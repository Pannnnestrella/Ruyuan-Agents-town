from __future__ import annotations

import unittest
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from interactive_server import create_app


ROOT = Path(__file__).resolve().parents[1]


class InteractiveApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_results = TemporaryDirectory()
        app = create_app(ROOT, results_root=self.temporary_results.name, planner_mode="heuristic")
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def tearDown(self):
        self.temporary_results.cleanup()

    def wait_for_task(self, task_id):
        for _ in range(100):
            response = self.client.get(f"/api/interactive/tasks/{task_id}")
            task = response.get_json()
            if task["status"] in {"succeeded", "failed"}:
                return task
            time.sleep(0.01)
        self.fail("round task did not complete")

    def test_browser_game_cycle(self):
        scenarios = self.client.get("/api/interactive/scenarios")
        self.assertEqual(scenarios.status_code, 200)
        self.assertEqual(scenarios.get_json()["scenarios"][0]["id"], "stormbound_inn")

        created = self.client.post(
            "/api/interactive/games",
            json={"scenario_id": "stormbound_inn", "game_id": "api-test", "seed": 7},
        )
        self.assertEqual(created.status_code, 201)
        body = created.get_json()
        self.assertEqual(len(body["cards"]), 3)
        self.assertEqual(body["empty_event"]["category"], "quiet")
        self.assertEqual(len(body["intel"]), 3)
        self.assertEqual(body["state"]["phase"], "intervention")

        intel = self.client.post(
            "/api/interactive/games/api-test/public-intel",
            json={"intel_id": body["intel"][0]["id"]},
        )
        self.assertEqual(intel.status_code, 201)
        self.assertEqual(len(intel.get_json()["state"]["public_intel_history"]), 1)

        notice = self.client.post(
            "/api/interactive/games/api-test/notices",
            json={"content": "所有住客暂留大堂。"},
        )
        self.assertEqual(notice.status_code, 201)

        card_id = body["cards"][0]["card_id"]
        selected = self.client.post(
            "/api/interactive/games/api-test/event-card",
            json={"card_id": card_id},
        )
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.get_json()["state"]["phase"], "ready")

        advanced = self.client.post("/api/interactive/games/api-test/rounds/advance", json={})
        self.assertEqual(advanced.status_code, 202)
        task = self.wait_for_task(advanced.get_json()["task_id"])
        self.assertEqual(task["status"], "succeeded")
        final_body = task["result"]
        self.assertEqual(final_body["state"]["round_number"], 1)
        self.assertEqual(final_body["state"]["phase"], "intervention")
        self.assertEqual(len(final_body["cards"]), 3)

    def test_private_truth_is_not_returned_by_state_api(self):
        created = self.client.post(
            "/api/interactive/games",
            json={"scenario_id": "stormbound_inn", "game_id": "privacy-test"},
        )
        text = created.get_data(as_text=True)
        self.assertNotIn("里八华细作以迟发毒针", text)
        self.assertNotIn("太一宫旧符牌", text)
        self.assertNotIn("killer_id", text)
        self.assertNotIn("你就是杀死陆成的凶手", text)

    def test_director_casebook_contains_seeded_truth_and_complete_character_files(self):
        self.client.post(
            "/api/interactive/games",
            json={"scenario_id": "stormbound_inn", "game_id": "director-truth", "seed": 17},
        )

        public = self.client.get("/api/interactive/games/director-truth").get_json()["state"]
        self.assertNotIn("director_casebook", public)
        self.assertNotIn("beliefs", next(iter(public["agents"].values())))

        response = self.client.get("/api/interactive/games/director-truth/director")
        self.assertEqual(response.status_code, 200)
        state = response.get_json()["state"]
        casebook = state["director_casebook"]
        self.assertTrue(casebook["killer_name"])
        self.assertTrue(casebook["motive"])
        self.assertTrue(casebook["method"])
        self.assertEqual(len(casebook["murder_chain"]), 5)
        self.assertEqual(len(casebook["characters"]), 6)
        self.assertGreaterEqual(len(casebook["objective_timeline"]), 20)
        self.assertEqual(sum(item["private"] for item in casebook["objective_timeline"]), 1)
        self.assertTrue(all(item["pregame_timeline"] for item in casebook["characters"]))
        self.assertEqual(sum(item["is_killer"] for item in casebook["characters"]), 1)
        self.assertTrue(all("beliefs" in item["current_state"] for item in casebook["characters"]))
        self.assertTrue(any(item["secrets"] for item in casebook["characters"]))
        self.assertIn("poison_needle", state["objects"])
        self.assertGreaterEqual(len(casebook["clue_map"]), 30)
        self.assertEqual(len(casebook["shared_deduction_foundation"]), 4)
        self.assertEqual(len(casebook["variant_guides"]), 3)
        self.assertEqual(sum(item["active"] for item in casebook["variant_guides"]), 1)
        self.assertEqual(
            next(item for item in casebook["variant_guides"] if item["active"])["killer_id"],
            casebook["killer_name"],
        )
        for guide in casebook["variant_guides"]:
            self.assertGreaterEqual(len(guide["chain"]), 4)
            self.assertTrue(guide["decisive_conclusion"])

    def test_live_map_and_director_pages_are_both_available(self):
        live = self.client.get("/interactive")
        director = self.client.get("/interactive/director")
        self.assertEqual(live.status_code, 200)
        self.assertEqual(director.status_code, 200)
        self.assertIn("实时地图", live.get_data(as_text=True))
        self.assertIn("导演台", director.get_data(as_text=True))

    def test_game_restores_after_service_restart(self):
        created = self.client.post(
            "/api/interactive/games",
            json={"scenario_id": "stormbound_inn", "game_id": "restart-test", "seed": 2},
        ).get_json()
        card_id = created["cards"][0]["card_id"]
        self.client.post("/api/interactive/games/restart-test/event-card", json={"card_id": card_id})
        queued = self.client.post("/api/interactive/games/restart-test/rounds/advance", json={})
        task = self.wait_for_task(queued.get_json()["task_id"])
        self.assertEqual(task["status"], "succeeded")

        restarted_app = create_app(ROOT, results_root=self.temporary_results.name, planner_mode="heuristic")
        restarted_app.config.update(TESTING=True)
        restarted_client = restarted_app.test_client()
        restored = restarted_client.get("/api/interactive/games/restart-test")
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.get_json()["state"]["round_number"], 1)

    def test_player_free_action_manual_host_choice_and_end_round_endpoints(self):
        created = self.client.post(
            "/api/interactive/games",
            json={
                "scenario_id": "stormbound_inn",
                "game_id": "player-api-test",
                "seed": 11,
                "player_agent_id": "广陵王",
            },
        ).get_json()
        token = created["player_token"]
        headers = {"X-Player-Token": token}

        player = created["player"]
        self.assertIsNone(player["active_event_card"])
        card_id = player["host_options"]["cards"][0]["card_id"]
        hosted = self.client.post(
            "/api/interactive/games/player-api-test/player/host-choice",
            headers=headers,
            json={"card_id": card_id, "intel_id": None},
        )
        self.assertEqual(hosted.status_code, 200)
        self.assertEqual(hosted.get_json()["player"]["phase"], "ready")

        player = hosted.get_json()["player"]
        destination = player["available_actions"]["moves"][0]["id"]
        free = self.client.post(
            "/api/interactive/games/player-api-test/player/actions",
            headers=headers,
            json={"action_type": "move", "location_id": destination},
        )
        free_task = self.wait_for_task(free.get_json()["task_id"])
        self.assertEqual(free_task["status"], "succeeded")
        self.assertEqual(free_task["result"]["player"]["action_step"], 0)

        major = self.client.post(
            "/api/interactive/games/player-api-test/player/actions",
            headers=headers,
            json={"action_type": "investigate", "location_id": destination},
        )
        major_task = self.wait_for_task(major.get_json()["task_id"])
        self.assertEqual(major_task["status"], "succeeded")
        self.assertEqual(major_task["result"]["player"]["action_step"], 1)

        ended = self.client.post(
            "/api/interactive/games/player-api-test/player/end-round",
            headers=headers,
            json={},
        )
        ended_task = self.wait_for_task(ended.get_json()["task_id"])
        self.assertEqual(ended_task["status"], "succeeded")
        self.assertEqual(ended_task["result"]["player"]["round_number"], 1)
        self.assertEqual(ended_task["result"]["player"]["phase"], "intervention")


if __name__ == "__main__":
    unittest.main()
