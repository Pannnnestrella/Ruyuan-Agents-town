#!/usr/bin/env python3
"""Resize one approved art module exactly, then assemble a repeat strip."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageOps


def fit_module(image: Image.Image, target: tuple[int, int], fit: str) -> Image.Image:
    source_w, source_h = image.size
    target_w, target_h = target
    if min(source_w, source_h, target_w, target_h) < 1:
        raise ValueError("source and target dimensions must be positive")
    if fit == "exact":
        if source_w * target_h != source_h * target_w:
            raise ValueError(
                f"exact fit refuses aspect change: {source_w}x{source_h} -> {target_w}x{target_h}"
            )
        return image.resize(target, Image.Resampling.LANCZOS)
    if fit != "cover":
        raise ValueError("fit must be exact or cover")
    factor = max(target_w / source_w, target_h / source_h)
    resized = image.resize(
        (max(1, round(source_w * factor)), max(1, round(source_h * factor))),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def assemble(
    source: Path,
    output: Path,
    *,
    module_width: int,
    module_height: int,
    repeat: int,
    fit: str,
    alternate_mirror: bool,
) -> dict[str, object]:
    if output.exists():
        raise ValueError(f"refusing to overwrite {output}")
    if module_width < 1 or module_height < 1 or repeat < 1:
        raise ValueError("module dimensions and repeat must be positive")
    with Image.open(source) as opened:
        source_size = opened.size
        module = fit_module(opened.convert("RGBA"), (module_width, module_height), fit)
    strip = Image.new("RGBA", (module_width * repeat, module_height), (0, 0, 0, 0))
    placements: list[dict[str, object]] = []
    for index in range(repeat):
        mirrored = bool(alternate_mirror and index % 2)
        tile = ImageOps.mirror(module) if mirrored else module
        x = index * module_width
        strip.alpha_composite(tile, (x, 0))
        placements.append({"index": index, "x": x, "mirrored": mirrored})
    output.parent.mkdir(parents=True, exist_ok=True)
    strip.save(output, format="PNG")
    return {
        "source": str(source),
        "source_size": list(source_size),
        "module_size": [module_width, module_height],
        "fit": fit,
        "alternate_mirror": alternate_mirror,
        "repeat": repeat,
        "output": str(output),
        "output_size": list(strip.size),
        "placements": placements,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--module-width", type=int, required=True)
    parser.add_argument("--module-height", type=int, required=True)
    parser.add_argument("--repeat", type=int, required=True)
    parser.add_argument("--fit", choices=("exact", "cover"), default="exact")
    parser.add_argument("--alternate-mirror", action="store_true")
    args = parser.parse_args()
    try:
        report = assemble(
            args.source,
            args.output,
            module_width=args.module_width,
            module_height=args.module_height,
            repeat=args.repeat,
            fit=args.fit,
            alternate_mirror=args.alternate_mirror,
        )
        print(json.dumps(report, ensure_ascii=False))
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
