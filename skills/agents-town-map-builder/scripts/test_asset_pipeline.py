from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

import prepare_map_assets
import extract_alpha
import validate_map
import apply_seam_door
import assemble_repeat_strip


class AssetPipelineTests(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[Path, dict, dict]:
        source = root / "source"
        source.mkdir()
        Image.new("RGB", (100, 80), "#59402f").save(source / "room-a.png")
        Image.new("RGB", (80, 100), "#354858").save(source / "room-b.png")
        for name, color in (("stairs-lower.png", "#c18a52"), ("stairs-upper.png", "#8f673f")):
            image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
            ImageDraw.Draw(image).rectangle((25, 10, 74, 89), fill=color)
            image.save(source / name)

        world = {
            "locations": [
                {"id": "a", "capacity": 1, "connections": ["b"]},
                {"id": "b", "capacity": 1, "connections": ["a"]},
            ]
        }
        binding = {
            "schema_version": 1,
            "projection": "orthogonal-top-down",
            "grid": {"columns": 2, "rows": 1, "tile_size": 64, "width": 128, "height": 64},
            "floors": [{"id": 1, "name": "one"}, {"id": 2, "name": "two"}],
            "rooms": {
                "a": {"floor": 1, "rect": {"x": 1, "y": 1, "w": 1, "h": 1}, "token_grid": {"columns": 1, "rows": 1}},
                "b": {"floor": 2, "rect": {"x": 1, "y": 1, "w": 1, "h": 1}, "token_grid": {"columns": 1, "rows": 1}},
            },
            "routes": [{
                "id": "a--b", "from": "a", "to": "b", "kind": "stairs",
                "segments": [
                    {"floor": 1, "points": [[32, 32], [48, 32]]},
                    {"floor": 2, "points": [[32, 32], [48, 32]]},
                ],
            }],
            "asset_manifest": {
                "schema_version": 1,
                "render_scale": 1,
                "source_root": "source",
                "prompt_ledger": "prompt-ledger.json",
                "normalized_root": "normalized",
                "composite_root": "composite",
                "max_upscale": 1.25,
                "assets": [
                    {"id": "room-a", "kind": "room-base", "room_id": "a", "source": "room-a.png", "fit": "cover", "anchor": "center", "z": 10, "required": True, "prompt_id": "room-a"},
                    {"id": "room-b", "kind": "room-base", "room_id": "b", "source": "room-b.png", "fit": "cover", "anchor": "center", "z": 10, "required": True, "prompt_id": "room-b"},
                    {"id": "stairs-lower", "kind": "portal", "route_id": "a--b", "floor": 1, "rect": {"x": 1, "y": 1, "w": 1, "h": 1}, "source": "stairs-lower.png", "fit": "contain", "anchor": "bottom-center", "trim_alpha": True, "requires_alpha": True, "z": 30, "required": True, "prompt_id": "stairs-lower"},
                    {"id": "stairs-upper", "kind": "portal", "route_id": "a--b", "floor": 2, "rect": {"x": 1, "y": 1, "w": 1, "h": 1}, "source": "stairs-upper.png", "fit": "contain", "anchor": "bottom-center", "trim_alpha": True, "requires_alpha": True, "z": 30, "required": True, "prompt_id": "stairs-upper"},
                ],
            },
        }
        path = root / "map_binding.json"
        path.write_text(json.dumps(binding), encoding="utf-8")
        return path, world, binding

    def test_manifest_and_exact_build(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, world, binding = self.make_fixture(root)
            self.assertEqual(validate_map.validate(world, binding, require_assets=True), [])
            report = prepare_map_assets.build(path, root / "build", None, False, False)
            self.assertEqual(report["floor_size"], [128, 64])
            for asset in report["assets"]:
                with Image.open(asset["normalized"]) as image:
                    self.assertEqual(image.size, (64, 64))
            for composite in report["composites"].values():
                with Image.open(composite) as image:
                    self.assertEqual(image.size, (128, 64))

    def test_excessive_upscale_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, _world, _binding = self.make_fixture(root)
            Image.new("RGB", (8, 8), "#000000").save(root / "source" / "room-a.png")
            with self.assertRaisesRegex(ValueError, "above max_upscale"):
                prepare_map_assets.build(path, root / "build", None, False, True)

    def test_calibration_subset_builds_only_selected_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, _world, _binding = self.make_fixture(root)
            report = prepare_map_assets.build(
                path, root / "build", None, False, False, {"room-a"}
            )
            built = [asset["id"] for asset in report["assets"] if asset["status"] == "built"]
            self.assertEqual(built, ["room-a"])
            self.assertTrue((root / "build" / "normalized" / "room-a.png").is_file())
            self.assertFalse((root / "build" / "normalized" / "room-b.png").exists())

    def test_missing_portal_floor_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _path, world, binding = self.make_fixture(root)
            binding["asset_manifest"]["assets"].pop()
            errors = validate_map.validate(world, binding, require_assets=True)
            self.assertTrue(any("missing required portal artwork on floors [2]" in error for error in errors))

    def test_checker_background_extracts_to_real_alpha(self):
        image = Image.new("RGB", (80, 60), "#fafafa")
        draw = ImageDraw.Draw(image)
        for y in range(0, 60, 10):
            for x in range(0, 80, 10):
                if (x // 10 + y // 10) % 2:
                    draw.rectangle((x, y, x + 9, y + 9), fill="#f2f2f2")
        draw.rectangle((25, 10, 54, 49), fill="#392b24")
        result = extract_alpha.extract(image, feather=0)
        self.assertEqual(result.mode, "RGBA")
        self.assertEqual(result.getpixel((0, 0))[3], 0)
        self.assertEqual(result.getpixel((40, 30))[3], 255)
        self.assertEqual(result.getchannel("A").getbbox(), (25, 10, 55, 50))

    def test_enclosed_checker_background_extracts_to_real_alpha(self):
        image = Image.new("RGB", (48, 48), (250, 250, 250))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8, 8, 39, 39), outline=(80, 55, 35), width=4)
        draw.rectangle((12, 12, 35, 35), fill=(244, 244, 244))
        draw.rectangle((20, 4, 27, 11), fill=(195, 170, 120))
        result = extract_alpha.extract(
            image,
            floor=215,
            spread=32,
            feather=0,
            include_enclosed=True,
        )
        self.assertEqual(result.getpixel((24, 24))[3], 0)
        self.assertEqual(result.getpixel((8, 24))[3], 255)
        self.assertEqual(result.getpixel((24, 6))[3], 255)

    def test_repeat_strip_resizes_before_mirrored_assembly(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "module.png"
            output = root / "strip.png"
            image = Image.new("RGB", (60, 40), "#806040")
            ImageDraw.Draw(image).rectangle((0, 0, 9, 39), fill="#ff0000")
            image.save(source)
            report = assemble_repeat_strip.assemble(
                source,
                output,
                module_width=30,
                module_height=20,
                repeat=4,
                fit="exact",
                alternate_mirror=True,
            )
            self.assertEqual(report["output_size"], [120, 20])
            with Image.open(output) as strip:
                self.assertEqual(strip.size, (120, 20))
                self.assertEqual(strip.getpixel((0, 10))[:3], (255, 0, 0))
                self.assertEqual(strip.getpixel((59, 10))[:3], (255, 0, 0))

    def test_seam_door_modifies_paired_safe_bands_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left_path = root / "left.png"
            right_path = root / "right.png"
            door_path = root / "door.png"
            left_output = root / "left-revised.png"
            right_output = root / "right-revised.png"
            Image.new("RGB", (100, 100), "#aa8855").save(left_path)
            Image.new("RGB", (140, 100), "#668899").save(right_path)
            door = Image.new("RGBA", (20, 50), (0, 0, 0, 0))
            ImageDraw.Draw(door).rectangle((0, 0, 19, 49), outline="#d0a060", width=2)
            door.save(door_path)
            report = apply_seam_door.apply(
                left_path,
                right_path,
                door_path,
                left_output,
                right_output,
                baseline=0.8,
                aperture_color=(28, 28, 30, 255),
            )
            self.assertEqual(report["baseline_y"], 80)
            with Image.open(left_output) as left, Image.open(right_output) as right:
                self.assertEqual(left.size, (100, 100))
                self.assertEqual(right.size, (140, 100))
                self.assertEqual(left.getpixel((99, 60)), (28, 28, 30, 255))
                self.assertEqual(right.getpixel((0, 60)), (28, 28, 30, 255))


if __name__ == "__main__":
    unittest.main()
