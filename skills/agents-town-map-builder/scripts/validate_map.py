#!/usr/bin/env python3
"""Validate an Agents Town world against its visual map binding."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PORTAL_ART_KINDS = ("stairs", "steps", "ladder", "hatch", "portal")
PROJECTIONS = {"orthogonal-top-down", "orthogonal-side-elevation"}
FIT_POLICIES = {"cover", "contain"}
ANCHORS = {
    "top-left", "top-center", "top-right",
    "center-left", "center", "center-right",
    "bottom-left", "bottom-center", "bottom-right",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def edge_key(left: str, right: str) -> tuple[str, str]:
    return tuple(sorted((left, right)))


def is_safe_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def validate_asset_manifest(
    binding: dict[str, Any],
    rooms: dict[str, Any],
    routes: list[dict[str, Any]],
    errors: list[str],
    *,
    required: bool,
) -> None:
    manifest = binding.get("asset_manifest")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("assets"), list):
        if required:
            errors.append("production asset_manifest.assets must be a non-empty list")
        return
    assets = manifest["assets"]
    if not assets:
        if required:
            errors.append("production asset_manifest.assets must be a non-empty list")
        return
    if manifest.get("schema_version") != 1:
        errors.append("asset_manifest.schema_version must be 1")
    render_scale = manifest.get("render_scale")
    if not isinstance(render_scale, int) or isinstance(render_scale, bool) or render_scale < 1:
        errors.append("asset_manifest.render_scale must be a positive integer")
    max_upscale = manifest.get("max_upscale", 1.25)
    if not isinstance(max_upscale, (int, float)) or isinstance(max_upscale, bool) or max_upscale < 1:
        errors.append("asset_manifest.max_upscale must be a number >= 1")
    for key in ("source_root", "normalized_root", "composite_root"):
        if not is_safe_relative_path(manifest.get(key)):
            errors.append(f"asset_manifest.{key} must be a safe relative path")
    if required and not is_safe_relative_path(manifest.get("prompt_ledger")):
        errors.append("asset_manifest.prompt_ledger must be a safe relative path")

    columns = binding["grid"]["columns"]
    rows = binding["grid"]["rows"]
    room_bases: dict[str, list[str]] = {room_id: [] for room_id in rooms}
    portal_art: dict[str, set[int]] = {}
    route_by_id = {str(route.get("id") or ""): route for route in routes}
    ids: set[str] = set()
    sources: set[str] = set()
    for index, asset in enumerate(assets):
        label = f"asset_manifest.assets[{index}]"
        if not isinstance(asset, dict):
            errors.append(f"{label} must be an object")
            continue
        asset_id = str(asset.get("id") or "")
        if not asset_id or asset_id in ids:
            errors.append(f"{label}: duplicate or empty asset id {asset_id!r}")
        ids.add(asset_id)
        source = asset.get("source")
        if not is_safe_relative_path(source):
            errors.append(f"{asset_id or label}: source must be a safe relative path")
        elif source in sources:
            errors.append(f"{asset_id or label}: duplicate source path {source!r}")
        sources.add(source)
        if asset.get("fit") not in FIT_POLICIES:
            errors.append(f"{asset_id or label}: fit must be cover or contain")
        if asset.get("anchor", "center") not in ANCHORS:
            errors.append(f"{asset_id or label}: invalid anchor")
        if not isinstance(asset.get("z"), int) or isinstance(asset.get("z"), bool):
            errors.append(f"{asset_id or label}: z must be an integer")
        if required and not str(asset.get("prompt_id") or ""):
            errors.append(f"{asset_id or label}: prompt_id is required for production")

        room_id = asset.get("room_id")
        has_explicit = "floor" in asset or "rect" in asset
        floor: Any = None
        if room_id is not None and has_explicit:
            errors.append(f"{asset_id or label}: use room_id or floor+rect, not both")
        elif room_id is not None:
            if room_id not in rooms:
                errors.append(f"{asset_id or label}: unknown room_id {room_id!r}")
            else:
                floor = rooms[room_id].get("floor")
        else:
            floor = asset.get("floor")
            rect = asset.get("rect") or {}
            values = [rect.get(key) for key in ("x", "y", "w", "h")]
            if not isinstance(floor, int) or not all(
                isinstance(value, int) and not isinstance(value, bool) and value > 0
                for value in values
            ):
                errors.append(f"{asset_id or label}: explicit floor/x/y/w/h must be positive integers")
            else:
                x, y, width, height = values
                if x + width - 1 > columns or y + height - 1 > rows:
                    errors.append(f"{asset_id or label}: explicit target is outside the grid")

        if asset.get("requires_alpha") and asset.get("fit") != "contain":
            errors.append(f"{asset_id or label}: alpha-required assets must use fit=contain")
        if asset.get("kind") == "room-base" and asset.get("required") is True:
            if room_id in room_bases:
                room_bases[room_id].append(asset_id)
            else:
                errors.append(f"{asset_id or label}: room-base must target a room_id")
        route_id = str(asset.get("route_id") or "")
        if route_id:
            if route_id not in route_by_id:
                errors.append(f"{asset_id or label}: unknown route_id {route_id!r}")
            elif asset.get("kind") == "portal" and asset.get("required") is True and isinstance(floor, int):
                portal_art.setdefault(route_id, set()).add(floor)

    if required:
        for room_id, base_ids in room_bases.items():
            if len(base_ids) != 1:
                errors.append(f"{room_id}: expected exactly one required room-base asset, found {len(base_ids)}")
        for route_id, route in route_by_id.items():
            route_kind = str(route.get("kind") or "").lower()
            if not any(token in route_kind for token in PORTAL_ART_KINDS):
                continue
            expected_floors = {segment.get("floor") for segment in route.get("segments", [])}
            actual_floors = portal_art.get(route_id, set())
            missing = expected_floors - actual_floors
            if missing:
                errors.append(f"{route_id}: missing required portal artwork on floors {sorted(missing)}")


def validate_prompt_ledger(binding_path: Path, binding: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    manifest = binding.get("asset_manifest") or {}
    try:
        ledger_rel = Path(manifest["prompt_ledger"])
        base = binding_path.parent.resolve()
        ledger_path = (base / ledger_rel).resolve()
        if not ledger_path.is_relative_to(base):
            return ["asset_manifest.prompt_ledger escapes the binding directory"]
        ledger = load_json(ledger_path)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        return [f"unable to load prompt ledger: {error}"]
    if ledger.get("schema_version") != 1:
        errors.append("prompt ledger schema_version must be 1")
    prompts = ledger.get("prompts")
    if not isinstance(prompts, dict):
        return errors + ["prompt ledger prompts must be an object"]
    expected = {
        str(asset.get("prompt_id") or "")
        for asset in manifest.get("assets", [])
        if isinstance(asset, dict)
    }
    missing = expected - set(prompts)
    if missing:
        errors.append(f"prompt ledger is missing prompt IDs: {sorted(missing)}")
    for prompt_id in expected & set(prompts):
        entry = prompts[prompt_id]
        if not isinstance(entry, dict) or not str(entry.get("prompt") or "").strip():
            errors.append(f"prompt ledger entry {prompt_id!r} requires a non-empty prompt")
    return errors


def validate(
    world: dict[str, Any],
    binding: dict[str, Any],
    *,
    require_assets: bool = False,
) -> list[str]:
    errors: list[str] = []
    locations = {item.get("id"): item for item in world.get("locations", [])}
    if None in locations:
        errors.append("every world location requires an id")
        locations.pop(None, None)

    grid = binding.get("grid") or {}
    columns, rows, tile_size = grid.get("columns"), grid.get("rows"), grid.get("tile_size")
    if binding.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if binding.get("projection") not in PROJECTIONS:
        errors.append(f"projection must be one of {sorted(PROJECTIONS)}")
    if not all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in (columns, rows, tile_size)):
        errors.append("grid columns, rows, and tile_size must be positive integers")
        return errors

    rooms = binding.get("rooms") or {}
    if set(rooms) != set(locations):
        errors.append(
            f"room IDs differ: missing={sorted(set(locations) - set(rooms))}, "
            f"extra={sorted(set(rooms) - set(locations))}"
        )
    occupied: dict[int, list[tuple[str, int, int, int, int]]] = {}
    for location_id, room in rooms.items():
        rect = room.get("rect") or {}
        values = [rect.get(key) for key in ("x", "y", "w", "h")]
        floor = room.get("floor")
        if not isinstance(floor, int) or not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
            errors.append(f"{location_id}: floor/x/y/w/h must be integers")
            continue
        x, y, width, height = values
        if min(values) < 1 or x + width - 1 > columns or y + height - 1 > rows:
            errors.append(f"{location_id}: room is outside the grid")
        for other_id, ox, oy, ow, oh in occupied.setdefault(floor, []):
            if x < ox + ow and x + width > ox and y < oy + oh and y + height > oy:
                errors.append(f"{location_id}: overlaps {other_id} on floor {floor}")
        occupied[floor].append((location_id, x, y, width, height))
        token_grid = room.get("token_grid") or {}
        slots = token_grid.get("columns", 0) * token_grid.get("rows", 0)
        capacity = int(locations.get(location_id, {}).get("capacity", 1))
        if slots < capacity:
            errors.append(f"{location_id}: {slots} token slots for capacity {capacity}")

    world_edges = {
        edge_key(location_id, connected)
        for location_id, location in locations.items()
        for connected in location.get("connections", [])
    }
    route_edges: set[tuple[str, str]] = set()
    route_ids: set[str] = set()
    routes = binding.get("routes", [])
    for route in routes:
        route_id = str(route.get("id") or "")
        source, target = route.get("from"), route.get("to")
        if not route_id or route_id in route_ids:
            errors.append(f"duplicate or empty route id: {route_id!r}")
        route_ids.add(route_id)
        if source not in locations or target not in locations or source == target:
            errors.append(f"{route_id}: invalid endpoints")
            continue
        edge = edge_key(source, target)
        if edge in route_edges:
            errors.append(f"{route_id}: duplicate edge {edge}")
        route_edges.add(edge)
        source_floor, target_floor = rooms.get(source, {}).get("floor"), rooms.get(target, {}).get("floor")
        segment_floors = {segment.get("floor") for segment in route.get("segments", [])}
        if source_floor != target_floor and route.get("kind") != "stairs":
            errors.append(f"{route_id}: cross-floor routes must use kind=stairs")
        if not {source_floor, target_floor}.issubset(segment_floors):
            errors.append(f"{route_id}: missing endpoint floor segment")
        for segment in route.get("segments", []):
            points = segment.get("points", [])
            if len(points) < 2 or any(not isinstance(point, list) or len(point) != 2 or not all(isinstance(value, (int, float)) for value in point) for point in points):
                errors.append(f"{route_id}: invalid segment points")

    if route_edges != world_edges:
        errors.append(
            f"route graph differs: missing={sorted(world_edges - route_edges)}, "
            f"extra={sorted(route_edges - world_edges)}"
        )
    validate_asset_manifest(binding, rooms, routes, errors, required=require_assets)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("world", type=Path)
    parser.add_argument("map_binding", type=Path)
    parser.add_argument(
        "--require-assets",
        action="store_true",
        help="require complete room-base and portal artwork manifest coverage",
    )
    args = parser.parse_args()
    try:
        binding = load_json(args.map_binding)
        errors = validate(
            load_json(args.world),
            binding,
            require_assets=args.require_assets,
        )
        if args.require_assets:
            errors.extend(validate_prompt_ledger(args.map_binding, binding))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("OK: map binding matches the world graph and geometry invariants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
