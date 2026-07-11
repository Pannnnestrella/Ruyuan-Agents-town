# -*- coding: utf-8 -*-
"""生成如鸢主题的五位默认 NPC（广陵王、孙策、傅融、左慈、刘辩）。

- 在 frontend/static/assets/village/agents/<名字>/ 下生成 agent.json；
- 素材暂借 角色选择文件夹 的像素小人，按角色做色调区分（后续可手动替换为如鸢立绘）；
- spatial.tree 由 maze.json 实时推导（已是广陵城地名）；
- 出生坐标取各自居所内不可碰撞的地砖；
- 同时生成 角色模板/agents/如鸢密探 模板（供启动器创建用户角色使用）。

幂等：重复运行会覆盖生成物。人设完整版见 data/lore/角色设定/。
"""
import colorsys
import json
import os
import shutil
from collections import defaultdict

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAZE = os.path.join(ROOT, "frontend", "static", "assets", "village", "maze.json")
AGENTS_DIR = os.path.join(ROOT, "frontend", "static", "assets", "village", "agents")
VISUAL_DIR = os.path.join(ROOT, "角色选择文件夹")
TEMPLATE_DIR = os.path.join(ROOT, "角色模板", "agents")

NPCS = {
    "广陵王": {
        "visual": "3", "hue": None, "age": 20,
        "living": ["广陵王府", "寝居"],
        "currently": "正在绣衣楼中翻阅各地送回的鸢报，绣云鸢飞云不知何时落在了她肩头。",
        "innate": "沉静从容，心思缜密，喜怒不形于色；待人温和有礼，但事关汉室与故人安危时果决狠辣。实为女扮男装的亲王，身世藏有巨大秘密，重要秘密绝不轻易示人，私下偶有少年心性。",
        "learned": "汉室宗亲，当代广陵王，朝廷密探机构绣衣楼的楼主，人称「楼主」。幼年在西蜀蜀山的隐鸢阁长大，师从阁主左慈，与刘辩、祢衡自幼同门。精于情报布局、剑术与谋略。称傅融为「傅副官」，称左慈为「师尊」，称刘辩为「陛下」，称孙策为「伯符」。",
        "lifestyle": "清晨即起在王府练剑，白日坐镇绣衣楼处理鸢报与据点重建事务，傍晚喜欢去市集酒肆听市井消息，偶尔偷偷给绣云鸢喂食。",
        "daily_plan": "清晨在王府练剑，上午去绣衣楼批阅鸢报，午后在议事厅与众人商议军政，傍晚到市集探听消息，夜间回寝居读书或与故人小酌。",
    },
    "傅融": {
        "visual": "5", "hue": 0.55, "age": 24,
        "living": ["绣衣楼", "鸢房"],
        "currently": "正在鸢房里核对这个月的账目，算盘珠子打得噼啪作响。",
        "innate": "精明干练，锱铢必较，刀子嘴豆腐心；说话常以省略号欲言又止，压力大时会把自己关进账房打算盘。对广陵王忠诚入骨、暗藏深情。极有动物缘，飞云绣球和野狸都喜欢他。",
        "learned": "绣衣楼副官，执掌鸢部（驯养绣云鸢传递情报），兼管全楼账目与采买。精于情报调度、账目核算与杀价。深知各地房价米价。怀疑天子刘辩曾主使加害广陵王，对他保持警惕。",
        "lifestyle": "天不亮就起身喂绣云鸢，白天在绣衣楼当值分发鸢报，黄昏掐着点去市集抢打折菜，夜里核账到深夜。",
        "daily_plan": "清晨喂飞云和绣球，上午在鸢房整理誊录鸢报，午后处理报销账目（常与人争执），黄昏去市集采买杀价，夜间对账记账。",
    },
    "孙策": {
        "visual": "4", "hue": 0.98, "age": 21,
        "living": ["议事厅", "军机堂"],
        "currently": "刚练完一趟枪，正琢磨着去酒肆叫一坛好酒，再找楼主聊聊江东的局势。",
        "innate": "豪爽张扬，武勇过人，爱笑爱闹讲义气；说话直来直去、带着江东人的爽利，对朋友掏心掏肺，对敌人毫不留情，偶尔孩子气地拉人做些胆大包天的事。",
        "learned": "江东孙氏长子，人称「小霸王」。父亲孙坚战死后率部平定扬州，杀门阀诛豪强，麾下有周瑜、太史慈、程普黄盖等将臣。此次代表江东渡江来访广陵，商议共抗黑山贼与丹阳盗之事。与广陵王是共历生死的挚友，唤她时亲昵不拘礼。",
        "lifestyle": "闻鸡起舞每日必练武，饭量惊人，喜欢拉人比武、看兵器、讲行军故事，晚上必要喝上几碗酒。",
        "daily_plan": "清晨在议事厅前空地练武，上午与广陵王商议江东与徐州军务，午后去匠作坊看兵器锻造或在市集闲逛，傍晚在酒肆豪饮，夜间巡视一圈才睡。",
    },
    "左慈": {
        "visual": "7", "hue": None, "desat": 0.35, "bright": 1.25, "age": 26,
        "living": ["隐鸢阁别院", "丹房"],
        "currently": "正在丹房照看新炼的一炉丹药，顺手给蜜糖罐贴上了写着「蜜坨坨」的纸条。",
        "innate": "仙风道骨，云淡风轻，语气温和悠远，像看透了世事；喜欢白色的东西，念旧，漫长岁月让他偶尔流露出深藏的孤寂与温柔，待晚辈弟子极有耐心。",
        "learned": "隐鸢阁阁主，世人谓之仙人之体、寿数不知凡几（外表约二十六岁）。精通道术、炼丹、观星与谶纬，知晓绣衣楼与隐鸢阁同源的古老秘辛。是广陵王的师尊，此次携隐鸢阁年度事务驻在广陵的别院，顺便照看昔日弟子。习惯把事务亲笔写在纸条上贴在显眼处。",
        "lifestyle": "作息随天时，白日炼丹画符、写信给蜀山的弟子们，喜欢在观星仪旁独坐，每年初雪之夜会独自待上一整夜。",
        "daily_plan": "清晨在丹房炼丹，上午整理隐鸢阁文书、给弟子回信，午后去王府看望广陵王或在医馆药庐与医者论道，入夜观星推演天机。",
    },
    "刘辩": {
        "visual": "6", "hue": 0.12, "age": 19,
        "living": ["乐坊", "琴堂"],
        "currently": "正倚在琴堂的软榻上温一壶酒，指尖无意识地在空中画着一道符箓的轨迹。",
        "innate": "风流笑意藏心事，看似散漫随性，实则敏感聪慧、观察入微；常以玩笑遮掩真心，欲言又止。偶尔心血来潮下厨，必定把厨房炸得一片狼藉。",
        "learned": "当今天子，灵帝长子。幼年不受宠，被送往太一宫由史子眇抚养如亲子，学得一手符篆之术（时灵时不灵）。此次以微服祈福为名暂离雒阳、客居广陵散心，城中人只知他是位姓刘的贵公子。与广陵王自幼在蜀山一同长大，情谊深厚而各有不能言说之事。",
        "lifestyle": "晏起，爱饮酒抚琴，喜欢混在市集人堆里听闲话，夜里常独自望着雒阳的方向出神。",
        "daily_plan": "上午在琴堂抚琴或练符篆，午后去市集闲逛、与人饮酒闲谈，傍晚找广陵王或孙策对弈小酌，夜间读书望月。",
    },
}

TEMPLATE_NPC = {
    "name": "如鸢密探",
    "visual": "1", "age": 18,
    "living": ["绣衣楼", "鸢房"],
    "currently": "刚到广陵城，正在绣衣楼中熟悉环境。",
    "innate": "机敏谨慎，眼观六路耳听八方。",
    "learned": "绣衣楼新晋密探，初来广陵报到，对城中人事还不熟悉。",
    "lifestyle": "作息规律，白天当值，晚上整理见闻。",
    "daily_plan": "上午在绣衣楼当值，午后外出探听消息，傍晚回楼复命，夜间休息。",
}


def load_maze():
    with open(MAZE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_tree(maze):
    """从 maze.json 推导完整 sector→arena→objects 树。"""
    tree = defaultdict(lambda: defaultdict(set))
    for t in maze["tiles"]:
        a = t.get("address", [])
        if len(a) >= 2:
            if len(a) >= 3:
                tree[a[0]][a[1]].add(a[2])
            else:
                _ = tree[a[0]][a[1]]
    return {s: {ar: sorted(objs) for ar, objs in arenas.items()} for s, arenas in tree.items()}


def find_spawns(maze, living, count=1):
    """取指定 sector/arena 内不可碰撞的地砖坐标（分散取样）。"""
    sector, arena = living
    coords = [
        t["coord"] for t in maze["tiles"]
        if not t.get("collision") and len(t.get("address", [])) >= 2
        and t["address"][0] == sector and t["address"][1] == arena
    ]
    if not coords:
        raise RuntimeError(f"找不到可站立地砖: {sector}/{arena}")
    step = max(1, len(coords) // (count + 1))
    return [coords[step * (i + 1) % len(coords)] for i in range(count)]


def tint_image(src, dst, hue=None, desat=None, bright=None):
    """按角色色调处理素材：hue=目标色相(0-1)，desat=饱和度倍率，bright=亮度倍率。"""
    im = Image.open(src).convert("RGBA")
    if hue is None and desat is None and bright is None:
        im.save(dst)
        return
    arr = np.asarray(im).astype(np.float32) / 255.0
    rgb, alpha = arr[..., :3], arr[..., 3:]
    maxc = rgb.max(axis=-1)
    minc = rgb.min(axis=-1)
    v = maxc
    s = np.where(maxc > 0, (maxc - minc) / np.maximum(maxc, 1e-6), 0)
    # 简化色相替换：以每像素明度/饱和度重建目标色相的颜色
    if hue is not None:
        base = np.array(colorsys.hsv_to_rgb(hue, 1.0, 1.0), dtype=np.float32)
        tinted = v[..., None] * (1 - s[..., None]) + v[..., None] * s[..., None] * base
        rgb = tinted
    if desat is not None:
        gray = rgb.mean(axis=-1, keepdims=True)
        rgb = gray + (rgb - gray) * desat
    if bright is not None:
        rgb = np.clip(rgb * bright, 0, 1)
    out = np.concatenate([np.clip(rgb, 0, 1), alpha], axis=-1)
    Image.fromarray((out * 255).astype(np.uint8), "RGBA").save(dst)


def make_agent(name, cfg, tree, coord, out_base):
    agent_dir = os.path.join(out_base, name)
    os.makedirs(agent_dir, exist_ok=True)
    agent = {
        "name": name,
        "portrait": f"assets/village/agents/{name}/portrait.png",
        "coord": list(coord),
        "currently": cfg["currently"],
        "scratch": {
            "age": cfg["age"],
            "innate": cfg["innate"],
            "learned": cfg["learned"],
            "lifestyle": cfg["lifestyle"],
            "daily_plan": cfg["daily_plan"],
        },
        "spatial": {
            "address": {"living_area": ["the Ville"] + cfg["living"]},
            "tree": {"the Ville": tree},
        },
    }
    with open(os.path.join(agent_dir, "agent.json"), "w", encoding="utf-8") as f:
        json.dump(agent, f, ensure_ascii=False, indent=2)
    # 占位素材来自已弃用的 角色选择文件夹；正式立绘由 fetch_ruyuan_art.py 生成。
    # 目标素材已存在或占位素材目录已删除时，跳过复制。
    src_dir = os.path.join(VISUAL_DIR, cfg["visual"])
    for fname in ("portrait.png", "texture.png"):
        src = os.path.join(src_dir, fname)
        dst = os.path.join(agent_dir, fname)
        if os.path.exists(src) and not os.path.exists(dst):
            tint_image(src, dst,
                       hue=cfg.get("hue"), desat=cfg.get("desat"), bright=cfg.get("bright"))
    return agent_dir


def main():
    maze = load_maze()
    tree = build_tree(maze)
    print("广陵城区域:", {s: list(a) for s, a in tree.items()})

    for name, cfg in NPCS.items():
        coord = find_spawns(maze, cfg["living"])[0]
        d = make_agent(name, cfg, tree, coord, AGENTS_DIR)
        print(f"生成 NPC: {name} @ {cfg['living']} coord={coord} -> {d}")

    # 用户角色模板（启动器 DEFAULT_TEMPLATE_AGENT 使用）
    cfg = TEMPLATE_NPC
    coord = find_spawns(maze, cfg["living"])[0]
    d = make_agent(cfg["name"], cfg, tree, coord, TEMPLATE_DIR)
    print(f"生成模板: {cfg['name']} -> {d}")


if __name__ == "__main__":
    main()
