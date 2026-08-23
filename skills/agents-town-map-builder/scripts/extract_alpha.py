#!/usr/bin/env python3
"""Extract real alpha from a dark asset on a baked light checker background."""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter


def background_candidate(pixel: tuple[int, int, int], floor: int, spread: int) -> bool:
    high = max(pixel)
    low = min(pixel)
    return low >= floor and high - low <= spread


def connected_background_mask(
    image: Image.Image,
    *,
    floor: int = 150,
    spread: int = 48,
) -> Image.Image:
    rgb = image.convert("RGB")
    pixels = rgb.load()
    width, height = rgb.size
    seen = bytearray(width * height)
    background = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()
    queue.extend((x, 0) for x in range(width))
    queue.extend((x, height - 1) for x in range(width))
    queue.extend((0, y) for y in range(height))
    queue.extend((width - 1, y) for y in range(height))
    while queue:
        x, y = queue.popleft()
        index = y * width + x
        if seen[index]:
            continue
        seen[index] = 1
        if not background_candidate(pixels[x, y], floor, spread):
            continue
        background[index] = 255
        if x:
            queue.append((x - 1, y))
        if x + 1 < width:
            queue.append((x + 1, y))
        if y:
            queue.append((x, y - 1))
        if y + 1 < height:
            queue.append((x, y + 1))
    return Image.frombytes("L", (width, height), bytes(255 - value for value in background))


def all_background_mask(
    image: Image.Image,
    *,
    floor: int = 215,
    spread: int = 32,
) -> Image.Image:
    """Remove matching light-neutral pixels even inside enclosed structural holes."""
    rgb = image.convert("RGB")
    values = (
        0 if background_candidate(pixel, floor, spread) else 255
        for pixel in rgb.get_flattened_data()
    )
    return Image.frombytes("L", rgb.size, bytes(values))


def decontaminate(
    image: Image.Image,
    alpha: Image.Image,
    *,
    matte: int = 252,
    alpha_floor: int = 12,
) -> Image.Image:
    rgb = image.convert("RGB")
    output = Image.new("RGBA", rgb.size, (0, 0, 0, 0))
    source_pixels = rgb.load()
    alpha_pixels = alpha.load()
    output_pixels = output.load()
    for y in range(rgb.height):
        for x in range(rgb.width):
            value = alpha_pixels[x, y]
            if value <= alpha_floor:
                continue
            if value >= 250:
                r, g, b = source_pixels[x, y]
                output_pixels[x, y] = (r, g, b, 255)
                continue
            amount = value / 255.0
            recovered = tuple(
                max(0, min(255, round((channel - matte * (1.0 - amount)) / amount)))
                for channel in source_pixels[x, y]
            )
            output_pixels[x, y] = (*recovered, value)
    return output


def extract(
    image: Image.Image,
    *,
    floor: int = 150,
    spread: int = 48,
    feather: float = 0.8,
    matte: int = 252,
    alpha_floor: int = 12,
    include_enclosed: bool = False,
) -> Image.Image:
    mask = (
        all_background_mask(image, floor=floor, spread=spread)
        if include_enclosed
        else connected_background_mask(image, floor=floor, spread=spread)
    )
    if feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    result = decontaminate(image, mask, matte=matte, alpha_floor=alpha_floor)
    extrema = result.getchannel("A").getextrema()
    if extrema[0] != 0 or extrema[1] != 255:
        raise ValueError(f"extraction did not produce full alpha range: {extrema}")
    return result


def make_preview(image: Image.Image, path: Path) -> None:
    panel_size = (384, 256)
    backgrounds = ((245, 242, 232, 255), (29, 34, 42, 255), (215, 41, 109, 255))
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError("cannot preview a fully transparent asset")
    subject = image.crop(bbox)
    factor = min((panel_size[0] - 24) / subject.width, (panel_size[1] - 24) / subject.height, 1.0)
    subject = subject.resize(
        (max(1, round(subject.width * factor)), max(1, round(subject.height * factor))),
        Image.Resampling.LANCZOS,
    )
    preview = Image.new("RGBA", (panel_size[0] * len(backgrounds), panel_size[1]), (0, 0, 0, 0))
    for index, color in enumerate(backgrounds):
        panel = Image.new("RGBA", panel_size, color)
        offset = ((panel.width - subject.width) // 2, (panel.height - subject.height) // 2)
        panel.alpha_composite(subject, offset)
        preview.alpha_composite(panel, (index * panel_size[0], 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    preview.convert("RGB").save(path, format="PNG")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--background-floor", type=int, default=150)
    parser.add_argument("--neutral-spread", type=int, default=48)
    parser.add_argument("--feather", type=float, default=0.8)
    parser.add_argument("--matte", type=int, default=252)
    parser.add_argument("--alpha-floor", type=int, default=12)
    parser.add_argument(
        "--include-enclosed",
        action="store_true",
        help="also remove matching near-white background inside closed frames and railing gaps",
    )
    args = parser.parse_args()
    try:
        with Image.open(args.source) as opened:
            original_size = opened.size
            result = extract(
                opened,
                floor=args.background_floor,
                spread=args.neutral_spread,
                feather=args.feather,
                matte=args.matte,
                alpha_floor=args.alpha_floor,
                include_enclosed=args.include_enclosed,
            )
        if args.output.exists():
            raise ValueError(f"refusing to overwrite {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        result.save(args.output, format="PNG")
        if args.preview:
            if args.preview.exists():
                raise ValueError(f"refusing to overwrite {args.preview}")
            make_preview(result, args.preview)
        alpha = result.getchannel("A")
        histogram = alpha.histogram()
        report = {
            "source": str(args.source),
            "output": str(args.output),
            "size": list(original_size),
            "alpha_extrema": list(alpha.getextrema()),
            "transparent_pixels": histogram[0],
            "translucent_pixels": sum(histogram[1:255]),
            "opaque_pixels": histogram[255],
            "content_bbox": list(alpha.getbbox() or ()),
            "parameters": {
                "background_floor": args.background_floor,
                "neutral_spread": args.neutral_spread,
                "feather": args.feather,
                "matte": args.matte,
                "alpha_floor": args.alpha_floor,
                "include_enclosed": args.include_enclosed,
            },
        }
        print(json.dumps(report, ensure_ascii=False))
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
