from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from agents_town.common.paths import discover_runtime_paths
from agents_town.interactive import GameService as CanonicalGameService
from agents_town.interactive import ScenarioLoader as CanonicalScenarioLoader
from agents_town.interactive.web.app import create_app
from modules.interactive import GameService, ScenarioLoader


ROOT = Path(__file__).resolve().parent.parent


class PackageCompatibilityTests(unittest.TestCase):
    def test_legacy_interactive_exports_point_to_canonical_types(self):
        self.assertIs(GameService, CanonicalGameService)
        self.assertIs(ScenarioLoader, CanonicalScenarioLoader)

    def test_interactive_resources_load_from_isolated_package(self):
        loaded = CanonicalScenarioLoader(ROOT).load("stormbound_inn")
        self.assertEqual("stormbound_inn", loaded.scenario["id"])
        self.assertEqual("guangling_inn", loaded.world["id"])

    def test_flask_uses_interactive_templates_and_scenarios(self):
        with TemporaryDirectory() as temp_dir:
            app = create_app(ROOT, results_root=temp_dir, planner_mode="heuristic")
            client = app.test_client()
            self.assertEqual(200, client.get("/interactive").status_code)
            payload = client.get("/api/interactive/scenarios").get_json()
            self.assertEqual("stormbound_inn", payload["scenarios"][0]["id"])

    def test_frozen_internal_resource_layout_is_discovered(self):
        with TemporaryDirectory() as temp_dir:
            distribution = Path(temp_dir)
            executable = distribution / "AI-Town.exe"
            packaged_root = distribution / "_internal"
            (packaged_root / "agents_town").mkdir(parents=True)
            with (
                mock.patch("agents_town.common.paths.sys.frozen", True, create=True),
                mock.patch("agents_town.common.paths.sys.executable", str(executable)),
            ):
                paths = discover_runtime_paths()
            self.assertEqual(packaged_root.resolve(), paths.resource_root)
            self.assertEqual((distribution / "results").resolve(), paths.results_root)


if __name__ == "__main__":
    unittest.main()
