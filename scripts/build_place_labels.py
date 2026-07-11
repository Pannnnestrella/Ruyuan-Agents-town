# -*- coding: utf-8 -*-
"""从 maze.json 计算各 sector/arena 的中心点，生成前端地名匾额标签数据 labels.json。

用法: python scripts/build_place_labels.py
输出: frontend/static/assets/village/labels.json
"""
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAZE = ROOT / "frontend/static/assets/village/maze.json"
OUT = ROOT / "frontend/static/assets/village/labels.json"


def center_of(tiles, tile_size):
    """取区域质心；若质心落在区域外（凹形），退回到离质心最近的区域内格子。"""
    cx = sum(t[0] for t in tiles) / len(tiles)
    cy = sum(t[1] for t in tiles) / len(tiles)
    if (round(cx), round(cy)) not in set(tiles):
        cx, cy = min(tiles, key=lambda t: (t[0] - cx) ** 2 + (t[1] - cy) ** 2)
    return round((cx + 0.5) * tile_size), round((cy + 0.5) * tile_size)


def main():
    maze = json.loads(MAZE.read_text(encoding="utf-8"))
    tile_size = maze["tile_size"]

    sector_tiles = defaultdict(list)
    arena_tiles = defaultdict(list)
    for t in maze["tiles"]:
        addr = t["address"]
        x, y = t["coord"]
        if len(addr) >= 1:
            sector_tiles[addr[0]].append((x, y))
        if len(addr) >= 2:
            arena_tiles[(addr[0], addr[1])].append((x, y))

    labels = {"sectors": [], "arenas": []}
    for name, tiles in sorted(sector_tiles.items()):
        x, y = center_of(tiles, tile_size)
        labels["sectors"].append({"name": name, "x": x, "y": y})
    for (sector, name), tiles in sorted(arena_tiles.items()):
        x, y = center_of(tiles, tile_size)
        labels["arenas"].append({"name": name, "sector": sector, "x": x, "y": y})

    OUT.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成 {OUT.relative_to(ROOT)}: {len(labels['sectors'])} sectors, {len(labels['arenas'])} arenas")
    for s in labels["sectors"]:
        print(f"  {s['name']}: ({s['x']}, {s['y']})")


if __name__ == "__main__":
    main()
