from __future__ import annotations

import copy
import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agents_town.interactive.application.game_service import GameService
from agents_town.interactive.infrastructure.scenario_loader import (
    ScenarioLoader,
    ScenarioValidationError,
)


ROOT = Path(__file__).resolve().parents[1]


class InteractiveMapBindingTests(unittest.TestCase):
    def setUp(self):
        self.loaded = ScenarioLoader(ROOT).load("stormbound_inn")

    def test_binding_covers_rooms_routes_and_capacity(self):
        binding = self.loaded.map_binding
        self.assertIsNotNone(binding)
        self.assertEqual(binding["grid"], {
            "columns": 12,
            "rows": 8,
            "tile_size": 64,
            "width": 768,
            "height": 512,
        })
        self.assertEqual(set(binding["rooms"]), {
            location["id"] for location in self.loaded.world["locations"]
        })
        self.assertEqual(len(binding["routes"]), 13)
        for floor in binding["floors"]:
            self.assert_public_asset_exists(floor["art"])
        for fixture in (binding.get("connection_fixtures") or {}).values():
            if isinstance(fixture, str):
                self.assert_public_asset_exists(fixture)
        capacities = {
            location["id"]: location["capacity"]
            for location in self.loaded.world["locations"]
        }
        for location_id, room in binding["rooms"].items():
            slots = room["token_grid"]["columns"] * room["token_grid"]["rows"]
            self.assertGreaterEqual(slots, capacities[location_id], location_id)

    def test_binding_rejects_missing_route_and_overlap(self):
        missing_route = copy.deepcopy(self.loaded.map_binding)
        missing_route["routes"].pop()
        with self.assertRaisesRegex(ScenarioValidationError, "map routes must match"):
            ScenarioLoader.validate(self.loaded.world, self.loaded.scenario, missing_route)

        overlapping = copy.deepcopy(self.loaded.map_binding)
        overlapping["rooms"]["stable"]["rect"] = dict(
            overlapping["rooms"]["courtyard"]["rect"]
        )
        with self.assertRaisesRegex(ScenarioValidationError, "overlap"):
            ScenarioLoader.validate(self.loaded.world, self.loaded.scenario, overlapping)

    def test_routes_separate_motion_paths_from_connector_visuals(self):
        binding = self.loaded.map_binding
        expected_modes = {
            "seam-door": 1,
            "paired-door": 9,
            "covered-passage": 1,
            "cellar-steps": 1,
            "stairs": 1,
        }
        actual_modes = {}
        for route in binding["routes"]:
            visual = route.get("visual") or {}
            mode = visual.get("mode")
            actual_modes[mode] = actual_modes.get(mode, 0) + 1
            self.assertTrue(visual.get("label"), route["id"])
            points = [
                point
                for segment in route["segments"]
                for point in segment["points"]
            ]
            length = sum(math.dist(first, second) for first, second in zip(points, points[1:]))
            if mode == "seam-door":
                self.assertEqual(length, 0, route["id"])
            else:
                self.assertGreater(length, 1, route["id"])
            for value in visual.get("endpoint_assets", {}).values():
                self.assert_public_asset_exists(value)
            if visual.get("endpoint_asset"):
                self.assert_public_asset_exists(visual["endpoint_asset"])
        self.assertEqual(actual_modes, expected_modes)

    def assert_public_asset_exists(self, url):
        url = url.split("?", 1)[0]
        prefix = "/static/"
        self.assertTrue(url.startswith(prefix), url)
        static_root = ROOT / "agents_town" / "interactive" / "resources" / "frontend" / "static"
        self.assertTrue((static_root / url.removeprefix(prefix)).is_file(), url)

    def test_all_runtime_views_expose_only_static_map_binding(self):
        with TemporaryDirectory() as results:
            service = GameService(ROOT, results_root=results)
            session = service.create_game(
                "stormbound_inn",
                game_id="map-view-test",
                player_agent_id="广陵王",
            )
            player = session.player_state(session.issued_player_token)
            for view in (session.public_state(), session.observer_state(), session.director_state(), player):
                self.assertEqual(view["map"], self.loaded.map_binding)
                text = str(view["map"])
                self.assertNotIn("killer_id", text)
                self.assertNotIn("agents", text)


if __name__ == "__main__":
    unittest.main()
