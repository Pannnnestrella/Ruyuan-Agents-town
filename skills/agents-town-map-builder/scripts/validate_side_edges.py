#!/usr/bin/env python3
"""Validate side-elevation route ports and optionally render direct-seam QA crops."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


EDGES = {"left", "right", "top", "bottom", "interior"}
JOINS = {"seam", "svg", "portal"}
VISUAL_MODES = {"seam-door", "paired-door", "covered-passage", "cellar-steps", "stairs"}
OPPOSITE = {("left", "right"), ("right", "left")}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def ratio(value: Any, *, allow_zero: bool = False) -> bool:
    lower = 0 if allow_zero else 0
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and lower <= value <= 1
        and (allow_zero or value > 0)
    )


def port_point(
    room: dict[str, Any], port: dict[str, Any], tile_size: float
) -> tuple[float, float]:
    if port.get("edge") == "interior":
        point = port.get("point")
        if (
            not isinstance(point, list)
            or len(point) != 2
            or not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in point)
        ):
            raise ValueError("interior port must declare numeric point: [x, y]")
        return float(point[0]), float(point[1])
    rect = room["rect"]
    left = (float(rect["x"]) - 1) * tile_size
    top = (float(rect["y"]) - 1) * tile_size
    width = float(rect["w"]) * tile_size
    height = float(rect["h"]) * tile_size
    edge = port["edge"]
    offset = float(port["offset"])
    if edge == "left":
        return left, top + offset * height
    if edge == "right":
        return left + width, top + offset * height
    if edge == "top":
        return left + offset * width, top
    if edge == "bottom":
        return left + offset * width, top + height
    raise ValueError(f"invalid port edge: {edge}")


def path_length(segments: list[dict[str, Any]]) -> float:
    total = 0.0
    for segment in segments:
        points = segment.get("points") or []
        for first, second in zip(points, points[1:]):
            total += math.dist(first, second)
    return total


def has_visible_expression(binding: dict[str, Any], route: dict[str, Any]) -> bool:
    visual = route.get("visual")
    if not isinstance(visual, dict) or visual.get("mode") not in VISUAL_MODES:
        return False
    mode = visual["mode"]
    if mode == "seam-door":
        manifest = binding.get("asset_manifest") or {}
        return bool(visual.get("endpoint_asset") or manifest.get("connection_kit"))
    if mode in {"cellar-steps", "stairs"}:
        assets = ((binding.get("asset_manifest") or {}).get("assets") or [])
        return bool(visual.get("endpoint_asset") or any(
            isinstance(asset, dict)
            and asset.get("kind") == "portal"
            and asset.get("route_id") == route.get("id")
            for asset in assets
        ))
    return True


def validate(
    binding: dict[str, Any],
    tolerance: float = 0.03,
    path_tolerance: float = 1.0,
    minimum_motion_length: float = 1.0,
) -> list[str]:
    errors: list[str] = []
    if binding.get("projection") != "orthogonal-side-elevation":
        return ["projection must be orthogonal-side-elevation"]
    rooms = binding.get("rooms")
    routes = binding.get("routes")
    if not isinstance(rooms, dict) or not isinstance(routes, list):
        return ["rooms must be an object and routes must be a list"]
    grid = binding.get("grid")
    if not isinstance(grid, dict):
        return ["grid must be an object"]
    try:
        tile_size = float(grid["tile_size"])
        canvas_width = float(grid["width"])
        canvas_height = float(grid["height"])
    except (KeyError, TypeError, ValueError):
        return ["grid tile_size, width, and height must be numeric"]

    for room_id, room in rooms.items():
        if not isinstance(room, dict):
            errors.append(f"{room_id}: room must be an object")
            continue
        baseline = room.get("movement_baseline")
        if not ratio(baseline):
            errors.append(f"{room_id}: movement_baseline must be a ratio in (0, 1]")
        edge_safe = room.get("edge_safe")
        if not isinstance(edge_safe, dict) or not all(
            ratio(edge_safe.get(edge), allow_zero=True) for edge in ("left", "right")
        ):
            errors.append(f"{room_id}: edge_safe.left/right must be ratios in [0, 1]")

    for index, route in enumerate(routes):
        if not isinstance(route, dict):
            errors.append(f"route[{index}] must be an object")
            continue
        route_id = str(route.get("id") or f"route[{index}]")
        join = route.get("visual_join")
        if join not in JOINS:
            errors.append(f"{route_id}: visual_join must be seam, svg, or portal")
        ports = route.get("ports")
        if not isinstance(ports, dict):
            errors.append(f"{route_id}: ports must contain from and to")
            continue
        checked: dict[str, dict[str, Any]] = {}
        endpoint_points: dict[str, tuple[float, float]] = {}
        for role in ("from", "to"):
            port = ports.get(role)
            endpoint = route.get(role)
            if not isinstance(port, dict):
                errors.append(f"{route_id}: missing {role} port")
                continue
            checked[role] = port
            if port.get("room") != endpoint or endpoint not in rooms:
                errors.append(f"{route_id}: {role} port room must equal route endpoint")
            if port.get("edge") not in EDGES:
                errors.append(f"{route_id}: {role} port has invalid edge")
            if not ratio(port.get("offset"), allow_zero=True):
                errors.append(f"{route_id}: {role} port offset must be in [0, 1]")
            if not ratio(port.get("aperture")):
                errors.append(f"{route_id}: {role} port aperture must be in (0, 1]")
            room = rooms.get(endpoint)
            if isinstance(room, dict) and port.get("edge") in EDGES:
                try:
                    point = port_point(room, port, tile_size)
                except (KeyError, TypeError, ValueError) as error:
                    errors.append(f"{route_id}: {role} {error}")
                else:
                    endpoint_points[role] = point
                    if not (0 <= point[0] <= canvas_width and 0 <= point[1] <= canvas_height):
                        errors.append(
                            f"{route_id}: {role} port point ({point[0]:.3f},{point[1]:.3f}) "
                            f"is outside canvas 0..{canvas_width:g}, 0..{canvas_height:g}"
                        )
            if (
                isinstance(room, dict)
                and port.get("edge") in {"left", "right"}
                and ratio(room.get("movement_baseline"))
                and ratio(port.get("offset"), allow_zero=True)
                and abs(float(port["offset"]) - float(room["movement_baseline"])) > tolerance
            ):
                errors.append(f"{route_id}: {role} side port does not align with its movement baseline")

        visual = route.get("visual")
        mode = visual.get("mode") if isinstance(visual, dict) else None
        if mode not in VISUAL_MODES:
            errors.append(
                f"{route_id}: visual.mode must be one of {', '.join(sorted(VISUAL_MODES))}"
            )
        elif not has_visible_expression(binding, route):
            errors.append(f"{route_id}: visual mode {mode} has no visible endpoint expression")
        if mode == "seam-door" and join != "seam":
            errors.append(f"{route_id}: seam-door requires visual_join seam")

        segments = route.get("segments")
        valid_segments = isinstance(segments, list) and bool(segments)
        if not valid_segments:
            errors.append(f"{route_id}: segments must be a non-empty animation-path list")
        else:
            for segment_index, segment in enumerate(segments):
                points = segment.get("points") if isinstance(segment, dict) else None
                if not isinstance(points, list) or len(points) < 2:
                    errors.append(
                        f"{route_id}: segment[{segment_index}] must contain at least two path points"
                    )
                    valid_segments = False
                    continue
                for point_index, point in enumerate(points):
                    if (
                        not isinstance(point, list)
                        or len(point) != 2
                        or not all(
                            isinstance(value, (int, float)) and not isinstance(value, bool)
                            for value in point
                        )
                    ):
                        errors.append(
                            f"{route_id}: segment[{segment_index}].points[{point_index}] "
                            "must be numeric [x, y]"
                        )
                        valid_segments = False
                        continue
                    if not (0 <= point[0] <= canvas_width and 0 <= point[1] <= canvas_height):
                        errors.append(
                            f"{route_id}: segment[{segment_index}].points[{point_index}] "
                            f"({point[0]},{point[1]}) is outside canvas "
                            f"0..{canvas_width:g}, 0..{canvas_height:g}"
                        )
            if valid_segments and set(endpoint_points) == {"from", "to"}:
                first_point = segments[0]["points"][0]
                last_point = segments[-1]["points"][-1]
                for role, actual in (("from", first_point), ("to", last_point)):
                    expected = endpoint_points[role]
                    deviation = math.dist(actual, expected)
                    if deviation > path_tolerance:
                        errors.append(
                            f"{route_id}: animation path {role} endpoint deviates from port by "
                            f"{deviation:.3f}px (maximum {path_tolerance:g}px)"
                        )
            if valid_segments:
                length = path_length(segments)
                permits_zero = mode == "seam-door" and join == "seam"
                if not permits_zero and length <= minimum_motion_length:
                    errors.append(
                        f"{route_id}: {mode or join} animation path length {length:.3f}px "
                        f"must exceed {minimum_motion_length:g}px"
                    )

        if join != "seam" or set(checked) != {"from", "to"}:
            continue
        first, second = checked["from"], checked["to"]
        if (first.get("edge"), second.get("edge")) not in OPPOSITE:
            errors.append(f"{route_id}: a direct seam must use opposite left/right edges")
            continue
        source = rooms.get(route.get("from"))
        target = rooms.get(route.get("to"))
        if not isinstance(source, dict) or not isinstance(target, dict):
            continue
        if source.get("floor") != target.get("floor"):
            errors.append(f"{route_id}: a direct seam cannot cross floors")
            continue
        try:
            first_xy = port_point(source, first, tile_size)
            second_xy = port_point(target, second, tile_size)
        except (KeyError, TypeError, ValueError):
            errors.append(f"{route_id}: cannot calculate seam coordinates")
            continue
        if max(abs(a - b) for a, b in zip(first_xy, second_xy)) > tolerance:
            errors.append(
                f"{route_id}: seam ports do not share a global coordinate "
                f"({first_xy[0]:.3f},{first_xy[1]:.3f}) != ({second_xy[0]:.3f},{second_xy[1]:.3f})"
            )
        if abs(float(first.get("aperture", 0)) - float(second.get("aperture", 0))) > tolerance:
            errors.append(f"{route_id}: seam aperture ratios differ")
    return errors


def room_asset_ids(binding: dict[str, Any]) -> dict[str, str]:
    assets = (binding.get("asset_manifest") or {}).get("assets") or []
    result: dict[str, str] = {}
    for asset in assets:
        if isinstance(asset, dict) and asset.get("kind") == "room-base" and asset.get("room_id"):
            result[str(asset["room_id"])] = str(asset.get("id") or "")
    return result


def edge_crop(image: Image.Image, edge: str) -> Image.Image:
    band = max(16, min(image.size) // 8)
    if edge == "right":
        return image.crop((image.width - band, 0, image.width, image.height))
    if edge == "left":
        return image.crop((0, 0, band, image.height))
    raise ValueError("QA crop supports left/right seam edges only")


def make_qa(binding: dict[str, Any], normalized_root: Path, output: Path, force: bool) -> int:
    asset_ids = room_asset_ids(binding)
    seam_routes = [route for route in binding.get("routes", []) if route.get("visual_join") == "seam"]
    if not seam_routes:
        raise ValueError("no direct seams are declared")
    if output.exists() and not force:
        raise ValueError(f"refusing to overwrite {output}; use --force")

    width, row_height, header = 640, 280, 24
    sheet = Image.new("RGB", (width, row_height * len(seam_routes)), (28, 30, 34))
    draw = ImageDraw.Draw(sheet)
    for row, route in enumerate(seam_routes):
        route_id = str(route.get("id") or f"route-{row}")
        ports = route["ports"]
        images: list[Image.Image] = []
        for role in ("from", "to"):
            room_id = str(route[role])
            asset_id = asset_ids.get(room_id)
            if not asset_id:
                raise ValueError(f"{route_id}: no room-base asset for {room_id}")
            path = normalized_root / f"{asset_id}.png"
            if not path.is_file():
                raise ValueError(f"{route_id}: missing normalized asset {path}")
            with Image.open(path) as opened:
                images.append(edge_crop(opened.convert("RGB"), ports[role]["edge"]))
        panel_height = row_height - header
        resized = []
        for item in images:
            factor = panel_height / item.height
            resized.append(item.resize((max(1, round(item.width * factor)), panel_height), Image.Resampling.NEAREST))
        pair_width = sum(item.width for item in resized)
        x = (width - pair_width) // 2
        y = row * row_height + header
        sheet.paste(resized[0], (x, y))
        sheet.paste(resized[1], (x + resized[0].width, y))
        draw.line((x + resized[0].width, y, x + resized[0].width, y + panel_height), fill=(255, 190, 72), width=1)
        draw.text((8, row * row_height + 5), route_id, fill=(235, 235, 235))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, format="PNG")
    return len(seam_routes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("map_binding", type=Path)
    parser.add_argument("--normalized-root", type=Path)
    parser.add_argument("--qa-output", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--tolerance", type=float, default=0.03)
    parser.add_argument("--path-tolerance", type=float, default=1.0)
    parser.add_argument("--minimum-motion-length", type=float, default=1.0)
    args = parser.parse_args()
    try:
        binding = load_json(args.map_binding)
        errors = validate(
            binding,
            args.tolerance,
            args.path_tolerance,
            args.minimum_motion_length,
        )
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        qa_count = 0
        if bool(args.normalized_root) != bool(args.qa_output):
            raise ValueError("--normalized-root and --qa-output must be used together")
        if args.normalized_root and args.qa_output:
            qa_count = make_qa(binding, args.normalized_root, args.qa_output, args.force)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    suffix = f"; rendered {qa_count} seam QA pairs" if qa_count else ""
    print(f"OK: side-elevation ports, motion paths, and connector visuals are valid{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
