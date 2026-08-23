#!/usr/bin/env python3
"""Normalize map art to grid-derived sizes and assemble exact floor PNGs."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image


ANCHORS = {
    "top-left", "top-center", "top-right",
    "center-left", "center", "center-right",
    "bottom-left", "bottom-center", "bottom-right",
}


@dataclass(frozen=True)
class Target:
    floor: int
    x: int
    y: int
    width: int
    height: int


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def safe_relative(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{label} must not be absolute or escape its root")
    return path


def resolve_under(base: Path, relative: Path, label: str) -> Path:
    resolved_base = base.resolve()
    candidate = (resolved_base / relative).resolve()
    if not candidate.is_relative_to(resolved_base):
        raise ValueError(f"{label} escapes {resolved_base}")
    return candidate


def target_for(asset: dict[str, Any], binding: dict[str, Any], scale: int) -> Target:
    room_id = asset.get("room_id")
    if room_id is not None:
        room = binding.get("rooms", {}).get(room_id)
        if not isinstance(room, dict):
            raise ValueError(f"{asset.get('id')}: unknown room_id {room_id!r}")
        floor = room.get("floor")
        rect = room.get("rect") or {}
    else:
        floor = asset.get("floor")
        rect = asset.get("rect") or {}
    values = [rect.get(key) for key in ("x", "y", "w", "h")]
    if not isinstance(floor, int) or not all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0
        for value in values
    ):
        raise ValueError(f"{asset.get('id')}: floor/x/y/w/h must be positive integers")
    x, y, width, height = values
    grid = binding["grid"]
    if x + width - 1 > grid["columns"] or y + height - 1 > grid["rows"]:
        raise ValueError(f"{asset.get('id')}: target is outside the grid")
    unit = grid["tile_size"] * scale
    return Target(floor, (x - 1) * unit, (y - 1) * unit, width * unit, height * unit)


def source_has_transparency(image: Image.Image) -> bool:
    if "A" not in image.getbands():
        return False
    extrema = image.getchannel("A").getextrema()
    return extrema[0] < 255


def trim_alpha(image: Image.Image) -> Image.Image:
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("asset is fully transparent")
    return image.crop(bbox)


def anchor_offset(anchor: str, box: tuple[int, int], item: tuple[int, int]) -> tuple[int, int]:
    box_w, box_h = box
    item_w, item_h = item
    vertical, horizontal = anchor.split("-", 1) if "-" in anchor else (anchor, anchor)
    if anchor == "center":
        vertical = horizontal = "center"
    x = 0 if horizontal == "left" else box_w - item_w if horizontal == "right" else (box_w - item_w) // 2
    y = 0 if vertical == "top" else box_h - item_h if vertical == "bottom" else (box_h - item_h) // 2
    return x, y


def normalize(
    image: Image.Image,
    target: Target,
    fit: str,
    anchor: str,
    max_upscale: float,
) -> tuple[Image.Image, dict[str, Any]]:
    source_w, source_h = image.size
    if source_w < 1 or source_h < 1:
        raise ValueError("source dimensions must be positive")
    if fit == "cover":
        factor = max(target.width / source_w, target.height / source_h)
    elif fit == "contain":
        factor = min(target.width / source_w, target.height / source_h)
    else:
        raise ValueError(f"unknown fit policy {fit!r}")
    if factor > max_upscale + 1e-9:
        raise ValueError(f"requires {factor:.3f}x upscale, above max_upscale={max_upscale:g}")

    resized_w = max(1, math.ceil(source_w * factor))
    resized_h = max(1, math.ceil(source_h * factor))
    resized = image.resize((resized_w, resized_h), Image.Resampling.LANCZOS)
    if fit == "cover":
        left = max(0, (resized_w - target.width) // 2)
        top = max(0, (resized_h - target.height) // 2)
        result = resized.crop((left, top, left + target.width, top + target.height))
        placement = {"crop": [left, top, left + target.width, top + target.height]}
    else:
        result = Image.new("RGBA", (target.width, target.height), (0, 0, 0, 0))
        offset = anchor_offset(anchor, result.size, resized.size)
        result.alpha_composite(resized, offset)
        placement = {"offset": list(offset)}
    operation = {
        "fit": fit,
        "scale": round(factor, 6),
        "resized": [resized_w, resized_h],
        **placement,
    }
    return result, operation


def validate_manifest(binding: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    grid = binding.get("grid") or {}
    if not all(isinstance(grid.get(key), int) and grid[key] > 0 for key in ("columns", "rows", "tile_size", "width", "height")):
        raise ValueError("binding grid dimensions must be positive integers")
    if grid["width"] != grid["columns"] * grid["tile_size"] or grid["height"] != grid["rows"] * grid["tile_size"]:
        raise ValueError("grid width/height must equal cells multiplied by tile_size")
    manifest = binding.get("asset_manifest")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("asset_manifest.schema_version must be 1")
    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("asset_manifest.assets must be a non-empty list")
    scale = manifest.get("render_scale")
    if not isinstance(scale, int) or isinstance(scale, bool) or scale < 1:
        raise ValueError("asset_manifest.render_scale must be a positive integer")
    return manifest, assets


def build(
    binding_path: Path,
    output_root: Path,
    source_override: Path | None,
    force: bool,
    check_only: bool,
    only_ids: set[str] | None = None,
) -> dict[str, Any]:
    binding = load_json(binding_path)
    manifest, assets = validate_manifest(binding)
    scale = manifest["render_scale"]
    max_upscale = float(manifest.get("max_upscale", 1.25))
    source_root = source_override.resolve() if source_override else resolve_under(
        binding_path.parent, safe_relative(manifest.get("source_root"), "source_root"), "source_root"
    )
    normalized_rel = safe_relative(manifest.get("normalized_root"), "normalized_root")
    composite_rel = safe_relative(manifest.get("composite_root"), "composite_root")
    normalized_root = resolve_under(output_root, normalized_rel, "normalized_root")
    composite_root = resolve_under(output_root, composite_rel, "composite_root")

    prepared: list[tuple[dict[str, Any], Target, Image.Image, dict[str, Any], Path]] = []
    report_assets: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_sources: set[Path] = set()
    errors: list[str] = []
    selected_assets = [
        asset for asset in assets
        if not only_ids or (isinstance(asset, dict) and str(asset.get("id") or "") in only_ids)
    ]
    if only_ids:
        found_ids = {str(asset.get("id") or "") for asset in selected_assets}
        unknown = only_ids - found_ids
        if unknown:
            raise ValueError(f"unknown --only asset IDs: {sorted(unknown)}")
    for index, asset in enumerate(selected_assets):
        if not isinstance(asset, dict):
            errors.append(f"asset[{index}] must be an object")
            continue
        asset_id = str(asset.get("id") or "")
        try:
            if not asset_id or asset_id in seen_ids or any(char in asset_id for char in "/\\") or asset_id in {".", ".."}:
                raise ValueError("asset id must be unique and filename-safe")
            seen_ids.add(asset_id)
            source_rel = safe_relative(asset.get("source"), f"{asset_id}.source")
            source = resolve_under(source_root, source_rel, f"{asset_id}.source")
            if source in seen_sources:
                raise ValueError(f"duplicate source file {source_rel}")
            seen_sources.add(source)
            if not source.is_file():
                if asset.get("required") is False:
                    report_assets.append({"id": asset_id, "status": "optional-source-missing", "source": str(source)})
                    continue
                raise ValueError(f"required source does not exist: {source}")
            target = target_for(asset, binding, scale)
            fit = asset.get("fit")
            anchor = asset.get("anchor", "center")
            if fit not in {"cover", "contain"}:
                raise ValueError("fit must be cover or contain")
            if anchor not in ANCHORS:
                raise ValueError(f"invalid anchor {anchor!r}")
            with Image.open(source) as opened:
                original_mode = opened.mode
                original_size = opened.size
                has_transparency = source_has_transparency(opened)
                if asset.get("requires_alpha") is True and not has_transparency:
                    raise ValueError("requires real transparent pixels, but source is opaque")
                image = opened.convert("RGBA")
            if asset.get("trim_alpha") is True:
                image = trim_alpha(image)
            normalized, operation = normalize(image, target, fit, anchor, max_upscale)
            if asset.get("kind") == "room-base" and normalized.getchannel("A").getextrema()[0] < 255:
                raise ValueError("room-base contains transparent holes after normalization")
            output = normalized_root / f"{asset_id}.png"
            entry = {
                "id": asset_id,
                "status": "checked" if check_only else "built",
                "source": str(source),
                "source_mode": original_mode,
                "source_size": list(original_size),
                "source_has_transparency": has_transparency,
                "target": {
                    "floor": target.floor,
                    "x": target.x,
                    "y": target.y,
                    "width": target.width,
                    "height": target.height,
                },
                "operation": operation,
                "normalized": str(output),
            }
            prepared.append((asset, target, normalized, entry, output))
            report_assets.append(entry)
        except (OSError, ValueError) as error:
            errors.append(f"{asset_id or f'asset[{index}]'}: {error}")
    if errors:
        raise ValueError("\n".join(errors))

    floor_size = (binding["grid"]["width"] * scale, binding["grid"]["height"] * scale)
    floor_ids = sorted({int(floor["id"]) for floor in binding.get("floors", [])})
    composite_paths = {floor: composite_root / f"floor-{floor}.png" for floor in floor_ids}
    report_path = output_root / "build-report.json"
    planned_outputs = [item[4] for item in prepared] + list(composite_paths.values()) + [report_path]
    if not check_only and not force:
        existing = [path for path in planned_outputs if path.exists()]
        if existing:
            raise ValueError("refusing to overwrite existing outputs; use a new version directory or --force: " + ", ".join(map(str, existing)))

    composites = {floor: Image.new("RGBA", floor_size, (0, 0, 0, 0)) for floor in floor_ids}
    for asset, target, normalized, _entry, _output in sorted(
        prepared, key=lambda item: (item[1].floor, int(item[0].get("z", 0)), assets.index(item[0]))
    ):
        if target.floor not in composites:
            raise ValueError(f"asset {asset.get('id')} targets undeclared floor {target.floor}")
        composites[target.floor].alpha_composite(normalized, (target.x, target.y))

    report = {
        "status": "checked" if check_only else "built",
        "binding": str(binding_path.resolve()),
        "source_root": str(source_root),
        "output_root": str(output_root.resolve()),
        "render_scale": scale,
        "floor_size": list(floor_size),
        "assets": report_assets,
        "composites": {str(floor): str(path) for floor, path in composite_paths.items()},
    }
    if not check_only:
        normalized_root.mkdir(parents=True, exist_ok=True)
        composite_root.mkdir(parents=True, exist_ok=True)
        for _asset, _target, normalized, _entry, output in prepared:
            normalized.save(output, format="PNG")
        for floor, composite in composites.items():
            composite.save(composite_paths[floor], format="PNG")
        output_root.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("map_binding", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="versioned build directory")
    parser.add_argument("--source-root", type=Path, help="override manifest source_root")
    parser.add_argument("--force", action="store_true", help="allow overwriting this build's generated outputs")
    parser.add_argument("--check-only", action="store_true", help="validate and calculate operations without writing files")
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="ASSET_ID",
        help="build only this asset (repeat for calibration subsets)",
    )
    args = parser.parse_args()
    try:
        report = build(
            args.map_binding.resolve(),
            args.output.resolve(),
            args.source_root,
            args.force,
            args.check_only,
            set(args.only) or None,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(
        f"OK: {len(report['assets'])} assets {report['status']}; "
        f"floor composites {report['floor_size'][0]}x{report['floor_size'][1]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
