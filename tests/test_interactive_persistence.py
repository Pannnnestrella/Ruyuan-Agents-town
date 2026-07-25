from __future__ import annotations

import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from modules.interactive.persistence import atomic_write_json


class AtomicPersistenceTests(unittest.TestCase):
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
