# -*- coding: utf-8 -*-
"""把地图与角色配置中的飞船主题地名替换为如鸢广陵城主题。

映射表：data/lore/地名映射.json（sector/arena/object 三级各自 1:1 映射）。
处理对象：
  1. frontend/static/assets/village/maze.json  —— tiles[*].address
  2. frontend/static/assets/village/agents/*/agent.json —— spatial.address / spatial.tree
  3. 角色模板/agents/*/agent.json —— 同上
世界名 "the Ville" 保留（compress.py 与启动器中硬编码）。
脚本幂等：已是新名的条目不受影响。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAPPING_PATH = os.path.join(ROOT, "data", "lore", "地名映射.json")


def load_mapping():
    with open(MAPPING_PATH, "r", encoding="utf-8") as f:
        m = json.load(f)
    # 合并为一张名字表：三级名称互不重复，直接统一替换
    table = {}
    for key in ("sectors", "arenas", "objects"):
        table.update(m[key])
    return table


def rename_list(names, table):
    return [table.get(n, n) for n in names]


def rename_tree(node, table):
    """spatial.tree 递归重命名：字典键与叶子列表元素都替换。"""
    if isinstance(node, dict):
        return {table.get(k, k): rename_tree(v, table) for k, v in node.items()}
    if isinstance(node, list):
        return rename_list(node, table)
    return node


def process_maze(path, table):
    with open(path, "r", encoding="utf-8") as f:
        maze = json.load(f)
    changed = 0
    for tile in maze.get("tiles", []):
        addr = tile.get("address")
        if addr:
            new = rename_list(addr, table)
            if new != addr:
                tile["address"] = new
                changed += 1
    with open(path, "w", encoding="utf-8") as f:
        json.dump(maze, f, ensure_ascii=False)
    print(f"maze.json: {changed} tiles renamed")


def process_agent(path, table):
    with open(path, "r", encoding="utf-8") as f:
        agent = json.load(f)
    spatial = agent.get("spatial", {})
    changed = False
    address = spatial.get("address", {})
    for k, v in list(address.items()):
        if isinstance(v, list):
            new = rename_list(v, table)
            if new != v:
                address[k] = new
                changed = True
    if "tree" in spatial:
        new_tree = rename_tree(spatial["tree"], table)
        if new_tree != spatial["tree"]:
            spatial["tree"] = new_tree
            changed = True
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(agent, f, ensure_ascii=False, indent=2)
    return changed


def main():
    table = load_mapping()
    maze_path = os.path.join(ROOT, "frontend", "static", "assets", "village", "maze.json")
    process_maze(maze_path, table)

    agent_dirs = [
        os.path.join(ROOT, "frontend", "static", "assets", "village", "agents"),
        os.path.join(ROOT, "角色模板", "agents"),
    ]
    for base in agent_dirs:
        if not os.path.isdir(base):
            continue
        n = 0
        for name in os.listdir(base):
            p = os.path.join(base, name, "agent.json")
            if os.path.isfile(p) and process_agent(p, table):
                n += 1
        print(f"{base}: {n} agent.json renamed")


if __name__ == "__main__":
    sys.exit(main())
