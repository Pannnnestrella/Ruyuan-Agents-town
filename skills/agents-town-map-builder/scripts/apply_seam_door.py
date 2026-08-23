#!/usr/bin/env python3
"""Apply one standardized doorway across two touching room-edge revisions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image


def apply(
    left_path: Path,
    right_path: Path,
    door_path: Path,
    left_output: Path,
    right_output: Path,
    *,
    baseline: float,
    aperture_color: tuple[int, int, int, int],
) -> dict[str, object]:
    if left_output.exists() or right_output.exists():
        raise ValueError("refusing to overwrite a seam revision")
    with Image.open(left_path) as opened:
        left = opened.convert("RGBA")
    with Image.open(right_path) as opened:
        right = opened.convert("RGBA")
    with Image.open(door_path) as opened:
        door = opened.convert("RGBA")
    if left.height != right.height:
        raise ValueError("touching room revisions must have the same pixel height")
    if door.width % 2:
        raise ValueError("door width must be even so the seam is deterministic")
    baseline_y = round(left.height * baseline)
    top = baseline_y - door.height
    if top < 0 or baseline_y > left.height:
        raise ValueError("door does not fit above the declared movement baseline")
    half = door.width // 2
    if half > min(left.width, right.width):
        raise ValueError("door half is wider than a room")

    inner_left = round(door.width * 0.16)
    inner_right = round(door.width * 0.84)
    inner_top = top + round(door.height * 0.12)
    inner_bottom = top + round(door.height * 0.94)
    left_inner_x = left.width - half + inner_left
    left.paste(aperture_color, (left_inner_x, inner_top, left.width, inner_bottom))
    right.paste(aperture_color, (0, inner_top, inner_right - half, inner_bottom))

    left_half = door.crop((0, 0, half, door.height))
    right_half = door.crop((half, 0, door.width, door.height))
    left.alpha_composite(left_half, (left.width - half, top))
    right.alpha_composite(right_half, (0, top))

    left_output.parent.mkdir(parents=True, exist_ok=True)
    right_output.parent.mkdir(parents=True, exist_ok=True)
    left.save(left_output, format="PNG")
    right.save(right_output, format="PNG")
    return {
        "left_input": str(left_path),
        "right_input": str(right_path),
        "door": str(door_path),
        "left_output": str(left_output),
        "right_output": str(right_output),
        "room_height": left.height,
        "baseline": baseline,
        "baseline_y": baseline_y,
        "door_size": list(door.size),
        "affected_left_bounds": [left.width - half, top, left.width, baseline_y],
        "affected_right_bounds": [0, top, half, baseline_y],
        "aperture_color": list(aperture_color),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("door", type=Path)
    parser.add_argument("left_output", type=Path)
    parser.add_argument("right_output", type=Path)
    parser.add_argument("--baseline", type=float, required=True)
    parser.add_argument("--aperture-rgb", nargs=3, type=int, default=(28, 28, 30))
    args = parser.parse_args()
    try:
        if not 0 < args.baseline <= 1:
            raise ValueError("baseline must be in (0, 1]")
        if not all(0 <= value <= 255 for value in args.aperture_rgb):
            raise ValueError("aperture RGB channels must be in [0, 255]")
        report = apply(
            args.left,
            args.right,
            args.door,
            args.left_output,
            args.right_output,
            baseline=args.baseline,
            aperture_color=(*args.aperture_rgb, 255),
        )
        print(json.dumps(report, ensure_ascii=False))
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
