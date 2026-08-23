#!/usr/bin/env python3

from __future__ import annotations

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).with_name("validate_side_edges.py")
SPEC = importlib.util.spec_from_file_location("validate_side_edges", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def binding() -> dict:
    return {
        "projection": "orthogonal-side-elevation",
        "grid": {"tile_size": 64, "width": 320, "height": 256},
        "rooms": {
            "a": {
                "floor": 1,
                "rect": {"x": 1, "y": 1, "w": 2, "h": 2},
                "movement_baseline": 0.8,
                "edge_safe": {"left": 0.1, "right": 0.1},
            },
            "b": {
                "floor": 1,
                "rect": {"x": 3, "y": 1, "w": 2, "h": 2},
                "movement_baseline": 0.8,
                "edge_safe": {"left": 0.1, "right": 0.1},
            },
        },
        "routes": [{
            "id": "a--b",
            "from": "a",
            "to": "b",
            "visual_join": "seam",
            "visual": {
                "mode": "seam-door",
                "label": "门",
                "endpoint_asset": "/static/door.png",
            },
            "ports": {
                "from": {"room": "a", "edge": "right", "offset": 0.8, "aperture": 0.2},
                "to": {"room": "b", "edge": "left", "offset": 0.8, "aperture": 0.2},
            },
            "segments": [{"floor": 1, "points": [[128, 102.4], [128, 102.4]]}],
        }],
        "asset_manifest": {"assets": [
            {"id": "room-a", "kind": "room-base", "room_id": "a"},
            {"id": "room-b", "kind": "room-base", "room_id": "b"},
        ]},
    }


def paired_binding() -> dict:
    value = binding()
    route = value["routes"][0]
    route["visual_join"] = "svg"
    route["visual"] = {"mode": "paired-door", "label": "门"}
    route["ports"]["to"] = {
        "room": "b",
        "edge": "right",
        "offset": 0.8,
        "aperture": 0.2,
    }
    route["segments"] = [{"floor": 1, "points": [[128, 102.4], [256, 102.4]]}]
    return value


class SideEdgeTests(unittest.TestCase):
    def test_valid_touching_seam(self) -> None:
        self.assertEqual(MODULE.validate(binding()), [])

    def test_rejects_misaligned_baseline(self) -> None:
        value = binding()
        value["routes"][0]["ports"]["to"]["offset"] = 0.5
        errors = MODULE.validate(value)
        self.assertTrue(any("baseline" in error or "global coordinate" in error for error in errors))

    def test_valid_paired_door_motion_path(self) -> None:
        self.assertEqual(MODULE.validate(paired_binding()), [])

    def test_rejects_missing_visual_mode(self) -> None:
        value = binding()
        value["routes"][0].pop("visual")
        errors = MODULE.validate(value)
        self.assertTrue(any("visual.mode" in error for error in errors))

    def test_rejects_zero_length_paired_door(self) -> None:
        value = paired_binding()
        value["routes"][0]["segments"][0]["points"] = [[128, 102.4], [128, 102.4]]
        errors = MODULE.validate(value)
        self.assertTrue(any("animation path length" in error for error in errors))

    def test_rejects_path_endpoint_deviation(self) -> None:
        value = paired_binding()
        value["routes"][0]["segments"][0]["points"][-1] = [192, 102.4]
        errors = MODULE.validate(value)
        self.assertTrue(any("deviates from port" in error for error in errors))

    def test_rejects_out_of_bounds_path_point(self) -> None:
        value = paired_binding()
        value["routes"][0]["segments"][0]["points"][0] = [-1, 102.4]
        errors = MODULE.validate(value)
        self.assertTrue(any("outside canvas" in error for error in errors))

    def test_rejects_interior_port_without_point(self) -> None:
        value = paired_binding()
        value["routes"][0]["ports"]["from"] = {
            "room": "a",
            "edge": "interior",
            "offset": 0.5,
            "aperture": 0.2,
        }
        errors = MODULE.validate(value)
        self.assertTrue(any("interior port must declare numeric point" in error for error in errors))

    def test_validate_does_not_mutate_binding(self) -> None:
        value = paired_binding()
        original = copy.deepcopy(value)
        MODULE.validate(value)
        self.assertEqual(value, original)

    def test_renders_edge_qa(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new("RGBA", (256, 128), (90, 60, 40, 255)).save(root / "room-a.png")
            Image.new("RGBA", (256, 128), (92, 62, 42, 255)).save(root / "room-b.png")
            output = root / "qa.png"
            count = MODULE.make_qa(binding(), root, output, False)
            self.assertEqual(count, 1)
            with Image.open(output) as opened:
                self.assertEqual(opened.size, (640, 280))


if __name__ == "__main__":
    unittest.main()
