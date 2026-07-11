# -*- coding: utf-8 -*-
"""批量添加《如鸢》密探角色到 AI 小镇。

数据源：
  - 人设：D:/Desktop/Pan_files/秋招/dhyUniverse/prompts/<名字>.txt（引言/秘辛/羁绊）
  - 职业：dhyUniverse data/processed/role_map.json
  - 出身：dhyUniverse data/processed/hometowns.json
  - 立绘：如鸢 biligame wiki（传唤.png=透明全身立绘 -> 地图贴图；突破前.png -> 头像）

产物：
  - frontend/static/assets/village/agents/<名字>/{agent.json, texture.png, portrait.png}
  - data/lore/形象素材/密探/<名字>-*.png（下载原图缓存，600px 缩略）
  - data/lore/密探名单.json（成功生成的角色列表，供更新启动器默认名单）

跳过已存在的五位默认 NPC。无立绘的角色回退用突破前做"纸牌"贴图；两者皆无则跳过该角色并记录。
"""
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from collections import defaultdict

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DHY = r"D:\Desktop\Pan_files\秋招\dhyUniverse"
PROMPTS = os.path.join(DHY, "prompts")
AGENTS_DIR = os.path.join(ROOT, "frontend", "static", "assets", "village", "agents")
ART_DIR = os.path.join(ROOT, "data", "lore", "形象素材", "密探")
MAZE = os.path.join(ROOT, "frontend", "static", "assets", "village", "maze.json")

SKIP = {"广陵王", "孙策", "傅融", "左慈", "刘辩"}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://wiki.biligame.com/"}
SHEET, CELL, CHAR_H = 3200, 640, 560

ROLE_LIVING = [
    (("武将", "将军", "剑士", "侠", "死士", "游俠", "游侠", "都督", "白马", "兵"), ("议事厅", "军机堂")),
    (("谋士", "文臣", "文官", "名士", "大儒", "学", "儒", "才女", "公子", "千金", "淑女", "诸侯", "牧", "王子", "宗亲"), ("广陵王府", "书画斋")),
    (("方士", "仙", "道", "巫", "阴阳", "隐士", "教主", "术士"), ("隐鸢阁别院", "丹房")),
    (("医",), ("医馆", "药庐")),
    (("乐", "歌", "琴", "舞"), ("乐坊", "琴堂")),
    (("商", "贾", "掌柜",), ("市集", "酒肆")),
    (("匠", "工", "铸"), ("匠作坊", "工坊")),
    (("密探", "刺客", "蜂", "雀", "山贼", "豪强", "头目"), ("绣衣楼", "鸢房")),
]

LIFESTYLE = {
    "议事厅": ("闻鸡即起，每日操练武艺，闲时擦拭兵刃、研读兵书，夜里巡视一圈才睡。",
             "清晨在议事厅前操练，上午研读兵书战策，午后去匠作坊看兵器或在城中走动，傍晚在酒肆用饭，夜间早歇。"),
    "广陵王府": ("晨起诵读经史，白日以笔墨会友，讲究衣冠仪度，夜里秉烛著述。",
              "上午在书画斋读书作文，午后与士人清谈或去乐坊听琴，傍晚在市集散步，夜间秉烛夜读。"),
    "隐鸢阁别院": ("作息随天时，白日炼丹画符、静坐修行，夜间观星，饮食清淡。",
               "清晨在丹房修行，上午研读道藏，午后采买药材或为人占卜，入夜在观星仪旁推演天机。"),
    "医馆": ("清晨采药制药，白日坐堂问诊，记录医案，夜间研读医书。",
           "上午在药庐坐堂诊病，午后炮制药材、整理医案，傍晚出诊，夜间研读医书。"),
    "乐坊": ("晏起，白日调弦度曲，喜与知音共赏，夜里常抚琴至深夜。",
           "上午在琴堂练琴度曲，午后与乐人切磋，傍晚为客人演奏，夜间整理乐谱。"),
    "市集": ("起早贪黑，白日在市集操持营生，善与人打交道，消息灵通。",
           "清晨盘点货物，上午在酒肆招呼客人，午后进货记账，傍晚生意最忙，夜间清点收入。"),
    "匠作坊": ("鸡鸣即起生火开炉，白日锤锻不辍，讲究手艺，夜间保养工具。",
            "清晨开炉，上午锻打器物，午后精修细作，傍晚交付订单，夜间保养炉具工具。"),
    "绣衣楼": ("昼伏夜出，行踪不定，白日在楼中当值整理情报，入夜外出探听消息。",
            "上午在鸢房整理情报，午后乔装外出探听消息，傍晚回楼复命，夜间轮值警戒。"),
}


def parse_prompt(path):
    text = open(path, encoding="utf-8").read()
    def section(title):
        m = re.search(rf"## {title}\n(.*?)(?=\n## |\Z)", text, re.S)
        return m.group(1).strip() if m else ""
    quote = section("角色引言").splitlines()[0].strip() if section("角色引言") else ""
    quote = re.sub(r"^言事章", "", quote)
    secrets = [l.lstrip("• ").strip() for l in section("角色秘辛").splitlines() if l.strip().startswith("•")]
    bonds = []
    for l in section("有过羁绊的人物").splitlines():
        m = re.match(r"- ([^（(]+)（([^）)]+)）", l.strip())
        if m:
            bonds.append(f"{m.group(1).strip()}（{m.group(2)}）")
    return quote, secrets, bonds


def pick_living(role):
    for keys, living in ROLE_LIVING:
        if any(k in role for k in keys):
            return living
    return ("市集", "酒肆")


def api(params):
    url = "https://wiki.biligame.com/yuan/api.php?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=30))


def query_images(names):
    """批量查询 传唤/突破前 图片原始 URL。返回 {角色: {kind: (url, filename)}}"""
    out = defaultdict(dict)
    titles = []
    for n in names:
        titles += [f"File:{n}-传唤.png", f"File:{n}-突破前.png"]
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        r = api({"action": "query", "titles": "|".join(batch),
                 "prop": "imageinfo", "iiprop": "url", "format": "json"})
        for p in r.get("query", {}).get("pages", {}).values():
            ii = p.get("imageinfo")
            if not ii:
                continue
            title = p["title"].split(":", 1)[1]
            who, kind = title[:-4].rsplit("-", 1)
            out[who][kind] = (ii[0]["url"], title)
    return out


def thumb_url(orig_url, filename, width):
    # https://patchwiki.biligame.com/images/yuan/f/fe/<hash>.png ->
    # https://patchwiki.biligame.com/images/yuan/thumb/f/fe/<hash>.png/600px-<filename>
    return orig_url.replace("/images/yuan/", "/images/yuan/thumb/") + \
        f"/{width}px-" + urllib.parse.quote(filename)


def fetch(url, dst):
    if os.path.exists(dst):
        return True
    try:
        req = urllib.request.Request(url, headers=UA)
        data = urllib.request.urlopen(req, timeout=40).read()
        open(dst, "wb").write(data)
        return True
    except Exception as e:
        print("  下载失败:", url, e)
        return False


def crop_content(im):
    im = im.convert("RGBA")
    bbox = im.split()[3].getbbox()
    return im.crop(bbox) if bbox else im


def build_texture_standee(src, dst):
    """透明立绘 -> 5x5 静态雪碧图。"""
    char = crop_content(Image.open(src))
    w, h = char.size
    scale = min(CHAR_H / h, (CELL - 40) / w)
    char = char.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    cell = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
    cell.paste(char, ((CELL - char.width) // 2, CELL - char.height), char)
    sheet = Image.new("RGBA", (SHEET, SHEET), (0, 0, 0, 0))
    for r in range(5):
        for c in range(5):
            sheet.paste(cell, (c * CELL, r * CELL))
    sheet.save(dst)


def build_texture_card(src, dst):
    """不透明立绘 -> 圆角纸牌样式贴图（回退方案）。"""
    im = Image.open(src).convert("RGBA")
    tw, th = 400, 560
    scale = max(tw / im.width, th / im.height)
    im = im.resize((int(im.width * scale) + 1, int(im.height * scale) + 1), Image.LANCZOS)
    x = (im.width - tw) // 2
    im = im.crop((x, 0, x + tw, th))
    mask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, tw - 1, th - 1], radius=40, fill=255)
    card = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    card.paste(im, (0, 0), mask)
    ImageDraw.Draw(card).rounded_rectangle([0, 0, tw - 1, th - 1], radius=40,
                                           outline=(214, 196, 158, 255), width=8)
    cell = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
    cell.paste(card, ((CELL - tw) // 2, CELL - th), card)
    sheet = Image.new("RGBA", (SHEET, SHEET), (0, 0, 0, 0))
    for r in range(5):
        for c in range(5):
            sheet.paste(cell, (c * CELL, r * CELL))
    sheet.save(dst)


def main():
    os.makedirs(ART_DIR, exist_ok=True)
    role_map = json.load(open(os.path.join(DHY, "data", "processed", "role_map.json"), encoding="utf-8"))["roles"]
    hometowns = {x["id"]: x.get("归属地", "") for x in
                 json.load(open(os.path.join(DHY, "data", "processed", "hometowns.json"), encoding="utf-8"))}

    maze = json.load(open(MAZE, encoding="utf-8"))
    tree = defaultdict(lambda: defaultdict(set))
    walkable = defaultdict(list)
    for t in maze["tiles"]:
        a = t.get("address", [])
        if len(a) >= 2:
            if len(a) >= 3:
                tree[a[0]][a[1]].add(a[2])
            else:
                _ = tree[a[0]][a[1]]
            if not t.get("collision"):
                walkable[(a[0], a[1])].append(t["coord"])
    full_tree = {s: {ar: sorted(o) for ar, o in arenas.items()} for s, arenas in tree.items()}

    names = [f[:-4] for f in os.listdir(PROMPTS) if f.endswith(".txt")]
    names = [n for n in names if n not in SKIP]
    print(f"候选角色 {len(names)} 位，查询立绘中……")
    images = query_images(names)

    ok, no_art = [], []
    arena_counter = defaultdict(int)
    for n in sorted(names):
        info = images.get(n, {})
        tex_kind = "传唤" if "传唤" in info else ("突破前" if "突破前" in info else None)
        por_kind = "突破前" if "突破前" in info else tex_kind
        if tex_kind is None:
            no_art.append(n)
            continue
        # 下载缩略图
        paths = {}
        good = True
        for kind in {tex_kind, por_kind}:
            url, fname = info[kind]
            dst = os.path.join(ART_DIR, f"{n}-{kind}.png")
            if not fetch(thumb_url(url, fname, 600), dst) and not fetch(url, dst):
                good = False
            paths[kind] = dst
        if not good:
            no_art.append(n)
            continue

        role = role_map.get(n) or "密探"
        if role == "男主角":
            role = "名士"
        living = pick_living(role)
        arena_counter[living] += 1
        coords = walkable[living]
        coord = coords[(arena_counter[living] * 37) % len(coords)]

        quote, secrets, bonds = parse_prompt(os.path.join(PROMPTS, n + ".txt"))
        home = hometowns.get(n, "")
        age = 18 + int(hashlib.md5(n.encode()).hexdigest(), 16) % 28

        innate = "，".join(filter(None, [f"江湖人称「{role}」" if role else ""])) or role
        innate = f"身份为{role}。" + ("私下面貌（据传）：" + " ".join(secrets[:2]) if secrets else "")
        learned = f"东汉末年《如鸢》世界观中的人物{('，出身' + home) if home else ''}，现客居广陵城。"
        if quote:
            learned += f"其言曰：「{quote}」"
        if bonds:
            learned += "与其有羁绊者：" + "、".join(bonds[:6]) + "。"
        lifestyle, daily = LIFESTYLE[living[0]]

        agent_dir = os.path.join(AGENTS_DIR, n)
        os.makedirs(agent_dir, exist_ok=True)
        if tex_kind == "传唤":
            build_texture_standee(paths[tex_kind], os.path.join(agent_dir, "texture.png"))
        else:
            build_texture_card(paths[tex_kind], os.path.join(agent_dir, "texture.png"))
        crop_content(Image.open(paths[por_kind])).save(os.path.join(agent_dir, "portrait.png"))

        agent = {
            "name": n,
            "portrait": f"assets/village/agents/{n}/portrait.png",
            "coord": list(coord),
            "currently": f"初到广陵城，正在{living[0]}的{living[1]}安顿，打量着这座城。",
            "scratch": {"age": age, "innate": innate, "learned": learned,
                        "lifestyle": lifestyle, "daily_plan": daily},
            "spatial": {"address": {"living_area": ["the Ville", living[0], living[1]]},
                        "tree": {"the Ville": full_tree}},
        }
        with open(os.path.join(agent_dir, "agent.json"), "w", encoding="utf-8") as f:
            json.dump(agent, f, ensure_ascii=False, indent=2)
        ok.append(n)
        print(f"√ {n} ({role} @ {living[0]}/{living[1]}, 贴图={tex_kind})")

    with open(os.path.join(ROOT, "data", "lore", "密探名单.json"), "w", encoding="utf-8") as f:
        json.dump({"added": ok, "no_art": no_art}, f, ensure_ascii=False, indent=2)
    print(f"\n完成：成功 {len(ok)} 位；无立绘跳过 {len(no_art)} 位：{no_art}")


if __name__ == "__main__":
    main()
