#!/usr/bin/env python3
"""Print grid-derived target sizes for a map binding's production assets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from prepare_map_assets import load_json, target_for, validate_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("map_binding", type=Path)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = parser.parse_args()
    try:
        binding = load_json(args.map_binding)
        manifest, assets = validate_manifest(binding)
        scale = manifest["render_scale"]
        rows = []
        for asset in assets:
            target = target_for(asset, binding, scale)
            logical_unit = binding["grid"]["tile_size"] * scale
            rows.append({
                "id": asset.get("id"),
                "kind": asset.get("kind"),
                "floor": target.floor,
                "rect": [
                    target.x // logical_unit + 1,
                    target.y // logical_unit + 1,
                    target.width // logical_unit,
                    target.height // logical_unit,
                ],
                "pixels": [target.width, target.height],
                "fit": asset.get("fit"),
                "source": asset.get("source"),
            })
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"render_scale": scale, "assets": rows}, ensure_ascii=False, indent=2))
    else:
        print(f"render_scale={scale}; assets={len(rows)}")
        print(f"{'ID':34} {'KIND':16} {'F':>2} {'RECT':>13} {'PIXELS':>12} {'FIT':>7}")
        for row in rows:
            rect = ",".join(map(str, row["rect"]))
            pixels = "x".join(map(str, row["pixels"]))
            print(f"{str(row['id']):34} {str(row['kind']):16} {row['floor']:>2} {rect:>13} {pixels:>12} {str(row['fit']):>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
