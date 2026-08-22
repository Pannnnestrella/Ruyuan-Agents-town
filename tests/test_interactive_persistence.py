from __future__ import annotations

import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from agents_town.interactive import ScenarioLoader
from agents_town.interactive.infrastructure.persistence import (
    atomic_write_json,
    game_state_from_dict,
)


ROOT = Path(__file__).resolve().parents[1]


class AtomicPersistenceTests(unittest.TestCase):
    def test_legacy_perspective_owner_field_loads_and_is_inferred(self):
        state = ScenarioLoader(ROOT).load("stormbound_inn").create_game_state(
            "legacy-perspective", seed=3
        )
        data = state.to_dict()
        owner_id = "傅融"
        authored = next(
            belief
            for belief in data["agents"][owner_id]["beliefs"]
            if "你" in belief["claim"]
        )
        authored.pop("perspective_owner_id", None)

        restored = game_state_from_dict(data)

        restored_belief = next(
            belief
            for belief in restored.agents[owner_id].beliefs
            if belief.belief_id == authored["belief_id"]
        )
        self.assertEqual(restored_belief.perspective_owner_id, owner_id)

    def test_transient_windows_permission_error_is_retried(self):
        with TemporaryDirectory() as temporary:
            destination = Path(temporary) / "state.json"
            real_replace = os.replace
            attempts = 0

            def flaky_replace(source, target):
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError(13, "temporarily locked", str(target))
                return real_replace(source, target)

            with mock.patch("modules.interactive.persistence.os.replace", side_effect=flaky_replace):
                atomic_write_json(destination, {"round": 2, "phase": "player_turn"})

            self.assertEqual(attempts, 3)
            self.assertEqual(
                json.loads(destination.read_text(encoding="utf-8")),
                {"round": 2, "phase": "player_turn"},
            )

    def test_longer_transient_lock_is_retried_before_failing(self):
        with TemporaryDirectory() as temporary:
            destination = Path(temporary) / "state.json"
            real_replace = os.replace
            attempts = 0

            def flaky_replace(source, target):
                nonlocal attempts
                attempts += 1
                if attempts < 12:
                    raise PermissionError(13, "temporarily locked", str(target))
                return real_replace(source, target)

            with (
                mock.patch(
                    "agents_town.interactive.infrastructure.persistence.os.replace",
                    side_effect=flaky_replace,
                ),
                mock.patch(
                    "agents_town.interactive.infrastructure.persistence.time.sleep"
                ),
            ):
                atomic_write_json(destination, {"round": 2})

            self.assertEqual(attempts, 12)
            self.assertEqual(
                json.loads(destination.read_text(encoding="utf-8")), {"round": 2}
            )

    def test_concurrent_saves_never_leave_partial_json(self):
        with TemporaryDirectory() as temporary:
            destination = Path(temporary) / "state.json"

            def save(index: int) -> None:
                atomic_write_json(destination, {
                    "index": index,
                    "events": [f"event-{index}-{item}" for item in range(200)],
                })

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(save, range(24)))

            saved = json.loads(destination.read_text(encoding="utf-8"))
            self.assertIn(saved["index"], range(24))
            self.assertEqual(len(saved["events"]), 200)
            self.assertFalse(list(Path(temporary).glob(".*.tmp")))


if __name__ == "__main__":
    unittest.main()
