# -*- coding: utf-8 -*-
"""从如鸢 biligame wiki 下载角色形象，替换五位 NPC 与建角模板的立绘。

- 原图存档到 data/lore/形象素材/<角色>/<表情>.png
- 每个角色生成：
    portrait.png —— 直接用指定形象
    texture.png  —— 3200x3200 的 5x5 雪碧图（心纸君缩放到高约560、底部居中对齐，
                    与旧素材的角色包围盒一致；静态形象填满全部 25 帧）
- 目标目录：frontend/static/assets/village/agents/<NPC>/ 与 角色模板/agents/<模板>/
"""
import os
import urllib.request

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART_DIR = os.path.join(ROOT, "data", "lore", "形象素材")
AGENTS_DIR = os.path.join(ROOT, "frontend", "static", "assets", "village", "agents")
TEMPLATE_DIR = os.path.join(ROOT, "角色模板", "agents")

BASE = "https://patchwiki.biligame.com/images/yuan/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
      "Referer": "https://wiki.biligame.com/"}

# hash 路径 -> (角色, 表情)
IMAGES = {
    # 孙策 心纸君
    "2/27/dwa1zv8qwmei1scxhabkm5vo1g2owrn.png": ("孙策", "惊讶"),
    "9/9e/hutbyebk5912pc4502ewq9vykyl7k7a.png": ("孙策", "开心"),
    "1/1e/bn39l04bx10a3pfw61lymy17njzer6x.png": ("孙策", "哭哭"),
    "3/30/5h92foqqkafag6wxckyr24689n3rs99.png": ("孙策", "疑惑"),
    "8/89/b4mmd6jfb8sviq2evw27s57ixbz72x7.png": ("孙策", "正常"),
    "0/0f/2k29sxzux32jxyozmcbxirde811xnq2.png": ("孙策", "害羞"),
    "f/f5/s09q3gzusa8ghio8zdulrnkdyj5kndi.png": ("孙策", "生气"),
    # 傅融 心纸君
    "d/d9/jmfjnjte3ez5axmw3cn2xr9wy0b6kps.png": ("傅融", "正常"),
    "9/98/22leslvwrm2k9424pmj3yp75zy58pqx.png": ("傅融", "白眼"),
    "4/4b/fb3yb9obb8y50atxj1r3brw6hbqxzjk.png": ("傅融", "惊讶"),
    "5/51/fxqpw186utnivebsmpqw0s9m3o3lupk.png": ("傅融", "开心"),
    "d/df/gsiwydc9mdioiymkb7hj1glg2shhcvc.png": ("傅融", "哭哭"),
    "0/07/oj6og1ddy7s7admwi4mwd57151y52tf.png": ("傅融", "生气"),
    "f/fc/4zzbohyxdwc53vhv8yjmtqdqq1uldn1.png": ("傅融", "疑惑"),
    # 左慈 心纸君
    "4/45/2yogrqf60xeujeokhc055yjv7ypp7b5.png": ("左慈", "皱眉"),
    "d/df/r5jja6uv3mh4wjhn35hv0gvnu148nz9.png": ("左慈", "惊讶"),
    "2/27/d4g0waez8e5lx5ktw3eax693mufbt42.png": ("左慈", "开心"),
    "3/35/lyfmfc64mxgqplwwm5vcg8ushdlngmf.png": ("左慈", "低落"),
    "b/b4/91ck2c597sy3wmw27tbp9o1mspu88i0.png": ("左慈", "生气"),
    "3/37/6blnktorrsuf5b5yecu2w2eg0f8ndu9.png": ("左慈", "疑惑"),
    "a/ac/gry0v2rrp1x3afc7icsr8k3szx2aqw0.png": ("左慈", "正常"),
    # 刘辩 心纸君
    "3/36/477n8jizl86cfrjhkg126rfdoj4uyaw.png": ("刘辩", "惶恐"),
    "2/20/exuwz737rxabi5yc1r652w5oeve6m0x.png": ("刘辩", "惊讶"),
    "d/dd/mb1q4qz4zd13qn77ksurzeqkmw0r8w7.png": ("刘辩", "开心"),
    "7/76/8xzk3ackyebawsmq7d3aywf32s318k0.png": ("刘辩", "哭哭"),
    "b/bf/trhonb4fa85n66fwzv6e3k7tqtixc9b.png": ("刘辩", "生气"),
    "2/27/431b8q8jkw87s8zfemj66lihk66zyxl.png": ("刘辩", "摇铃"),
    "1/19/d7d23rqkj5fw3p68upwo4ljbi4dm198.png": ("刘辩", "疑惑"),
    "e/e9/mgxln3hxo1mx9b9ahwcbuhk8qdu0xnq.png": ("刘辩", "正常"),
    "0/0d/60qrpmu2g3fxxdvy22ksysx2n4huw90.png": ("刘辩", "流汗"),
    # 广陵王
    "e/e5/fa6a3j5hsx8z8cthvws0g3daaay9xfz.png": ("广陵王", "心纸君"),
    "4/4c/qgw58m9q7fxvs6m55z6epn8ywpj64rb.png": ("广陵王", "立绘"),
    "d/dc/m1x2u91st6pzx4avrjuc4fzw81xj37s.png": ("广陵王", "头像-微笑"),
    "2/28/bc41xebesxcrdgjw49406vpffs2oh21.png": ("广陵王", "头像-严肃"),
    "e/e3/tmhvgun3svb1tyr5z7kwsm9uzcm3acl.png": ("广陵王", "头像-冷笑"),
    "c/cc/d27xzt8u2x0h448luvybpxz7li9gz4p.png": ("广陵王", "头像-开心"),
    # 建角模板形象
    "f/f1/l20rkb4yf5tb8kn7o5o8n98jnh20cll.png": ("袁基", "正常"),
    "a/ab/j1fm6sucx1tg2ku6h0zz9i0jp8rpmnt.png": ("王子乔", "正常"),
}

# 角色 -> (texture 源表情, portrait 源表情, 输出目录)
TARGETS = {
    "孙策": ("正常", "正常", AGENTS_DIR),
    "傅融": ("正常", "正常", AGENTS_DIR),
    "左慈": ("正常", "正常", AGENTS_DIR),
    "刘辩": ("正常", "正常", AGENTS_DIR),
    "广陵王": ("心纸君", "立绘", AGENTS_DIR),
}
# 建角模板（角色模板/agents 下）
TEMPLATE_TARGETS = {
    "如鸢密探": ("王子乔", "正常"),
    "如鸢密探·袁基": ("袁基", "正常"),
}

SHEET, CELL = 3200, 640
CHAR_H = 560  # 与旧素材角色高度一致（底部对齐）


def fetch(path, dst):
    if os.path.exists(dst):
        return
    req = urllib.request.Request(BASE + path, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r, open(dst, "wb") as f:
        f.write(r.read())


def crop_content(im):
    im = im.convert("RGBA")
    bbox = im.split()[3].getbbox()
    return im.crop(bbox) if bbox else im


def build_texture(src_png, dst_png):
    """把单张心纸君铺成 5x5 雪碧图（静态，无行走动画）。"""
    char = crop_content(Image.open(src_png))
    w, h = char.size
    scale = CHAR_H / h
    char = char.resize((max(1, int(w * scale)), CHAR_H), Image.LANCZOS)
    cw, chh = char.size
    cell = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
    cell.paste(char, ((CELL - cw) // 2, CELL - chh), char)
    sheet = Image.new("RGBA", (SHEET, SHEET), (0, 0, 0, 0))
    for r in range(5):
        for c in range(5):
            sheet.paste(cell, (c * CELL, r * CELL))
    sheet.save(dst_png)


def build_portrait(src_png, dst_png):
    im = crop_content(Image.open(src_png))
    im.save(dst_png)


def main():
    os.makedirs(ART_DIR, exist_ok=True)
    for path, (who, mood) in IMAGES.items():
        d = os.path.join(ART_DIR, who)
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, f"{mood}.png")
        fetch(path, dst)
        print("下载:", who, mood)

    for name, (tex_mood, por_mood, base) in TARGETS.items():
        agent_dir = os.path.join(base, name)
        os.makedirs(agent_dir, exist_ok=True)
        build_texture(os.path.join(ART_DIR, name, f"{tex_mood}.png"),
                      os.path.join(agent_dir, "texture.png"))
        build_portrait(os.path.join(ART_DIR, name, f"{por_mood}.png"),
                       os.path.join(agent_dir, "portrait.png"))
        print("生成素材:", name)

    for tpl, (who, mood) in TEMPLATE_TARGETS.items():
        agent_dir = os.path.join(TEMPLATE_DIR, tpl)
        os.makedirs(agent_dir, exist_ok=True)
        src = os.path.join(ART_DIR, who, f"{mood}.png")
        build_texture(src, os.path.join(agent_dir, "texture.png"))
        build_portrait(src, os.path.join(agent_dir, "portrait.png"))
        print("生成模板素材:", tpl, "<-", who)


if __name__ == "__main__":
    main()
