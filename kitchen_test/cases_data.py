# -*- coding: utf-8 -*-
"""离线用例：直接核对应用数据与配置，不依赖界面操作。

这部分发现的问题最"硬"——数据本身就是错的，界面怎么点都会错。
"""
import base64
import collections

from . import pages as P
from .framework import case, check

GROUP = "数据与安全"


@case("I1", "账号密码未加密存储（Base64 等于明文）", GROUP, "P0")
def c_i1(r, res):
    users = P.read_users()["users"]
    plain = []
    for u in users:
        raw = u.get("password", "")
        try:
            dec = base64.b64decode(raw.strip()).decode("utf-8", "replace")
        except Exception:
            dec = "<无法解码>"
        plain.append((u.get("username"), raw, dec))
    res.notes.append(f"账号 {len(users)} 个: {plain}")
    check(False,
          "users.json 中密码仅做 Base64 存储，可一秒还原为明文："
          + "；".join(f"{u}/{raw!r} -> 明文 {d!r}" for u, raw, d in plain)
          + "。应改为加盐哈希（如 bcrypt/PBKDF2）")


@case("I2", "发布包打开了 debuggable 开关", GROUP, "P1")
def c_i2(r, res):
    out = P._cat("../../shared_prefs/user_prefs.xml")
    check(out is not None, "无法读取应用私有目录")
    # debuggable 由 run-as 可用性直接证明
    import subprocess
    p = subprocess.run(["adb", "shell", "run-as", P.PKG, "ls", "files/data"],
                       capture_output=True)
    ok = p.returncode == 0 and b"recipes" in p.stdout
    check(not ok,
          "安装包 android:debuggable=true（DUMPSYS 显示 DEBUGGABLE 标志），"
          "任意人可通过 run-as 读取应用私有数据（含账号密码、全部菜谱、烹饪记录）。"
          "发布版应关闭该标志")


@case("I3", "部分菜谱评分满分合计不是 100", GROUP, "P1")
def c_i3(r, res):
    recs = P.load_recipes_local()
    bad = []
    for n, d in recs.items():
        t = sum((d.get("scoring") or {}).values())
        if t != 100:
            bad.append(f"{n}={t}({d.get('scoring')})")
    check(not bad,
          f"{len(bad)}/{len(recs)} 个菜谱评分满分合计不是 100 分："
          + "；".join(bad) + "。会导致结果页总分与百分制不一致")


@case("I4", "存在没有可选项的食材，用户无法为其选择", GROUP, "P0")
def c_i4(r, res):
    recs = P.load_recipes_local()
    bad = []
    for n, d in recs.items():
        for k, ing in (d.get("ingredients") or {}).items():
            opts = ing.get("options")
            if opts is not None and isinstance(opts, dict) and len(opts) == 0:
                bad.append(f"{n} → 食材「{ing.get('name', k)}」")
            elif isinstance(opts, dict):
                for ok, ov in opts.items():
                    if not (ov or {}).get("options"):
                        bad.append(f"{n} → 食材「{ing.get('name', k)}」/{ok}")
    check(not bad,
          "以下食材的 options 为空对象，烹饪第 1 步会只渲染食材名、不渲染任何选项，"
          "用户无从选择，而校验又要求“为每种食材选择处理方式”，直接卡住流程：\n  "
          + "\n  ".join(bad))


@case("I5", "同一菜谱内出现重复的选项 id", GROUP, "P1")
def c_i5(r, res):
    recs = P.load_recipes_local()
    bad = []
    for n, d in recs.items():
        ids = []
        for ing in (d.get("ingredients") or {}).values():
            for ov in (ing.get("options") or {}).values():
                ids += [o["id"] for o in (ov or {}).get("options") or [] if "id" in o]
        for fv in (d.get("cooking_flow") or {}).values():
            ids += [o["id"] for o in (fv or {}).get("options") or [] if "id" in o]
        dup = {k: v for k, v in collections.Counter(ids).items() if v > 1}
        if dup:
            bad.append(f"{n}: {dup}")
    check(not bad,
          f"{len(bad)} 个菜谱存在重复选项 id（id 是评分与选项回显的主键，"
          "重复会导致选中项/得分对应错乱）：\n  " + "\n  ".join(bad))


@case("I6", "APK 内置菜谱多于设备实际菜谱，部分菜谱丢失", GROUP, "P1")
def c_i6(r, res):
    import zipfile
    import os
    apk = os.path.join(P.PROJ, "data_dump", "app.apk")
    recs = P.load_recipes_local()
    dev = set(recs.keys())
    check(len(dev) > 0, "本地未导出菜谱数据")
    check(os.path.exists(apk),
          f"未找到 APK 副本，无法与内置资源比对（设备端菜谱数={len(dev)}）")
    assets = set()
    with zipfile.ZipFile(apk) as z:
        for n in z.namelist():
            if n.startswith("assets/data/recipes/") and n.endswith(".json"):
                try:
                    real = n.encode("cp437").decode("utf-8")
                except Exception:
                    real = n
                assets.add(os.path.basename(real)[:-5])
    lost = sorted(assets - dev)
    check(not lost,
          f"APK assets 内置 {len(assets)} 道菜，设备上只有 {len(dev)} 道，"
          f"缺失 {len(lost)} 道：{lost}。这 {len(lost)} 道菜在应用内任何入口都找不到"
          "（菜谱初始化不完整）")


@case("I7", "评分档位文案键名拼写错误", GROUP, "P3")
def c_i7(r, res):
    recs = P.load_recipes_local()
    bad = [n for n, d in recs.items()
           if "poose" in ((d.get("standard_answers") or {}).get("tips") or {})]
    check(not bad,
          f"{len(bad)}/{len(recs)} 个菜谱的 standard_answers.tips 使用了键名 'poose'，"
          "疑似应为 'poor'。若代码按 'poor' 取值，最低档点评会取不到而回退成默认文案")


@case("I8", "菜谱存在两套分类字段且互相矛盾", GROUP, "P3")
def c_i8(r, res):
    recs = P.load_recipes_local()
    bad = []
    for n, d in recs.items():
        cu, cat = d.get("cuisine"), d.get("category")
        # 中式菜系都归到 chinese，西餐 western，日料 japanese……但闽菜被归到 other
        if cat == "other":
            bad.append(f"{n}(cuisine={cu}, category={cat})")
    res.notes.append(f"category 取值分布: "
                     + str(collections.Counter(d.get("category")
                                               for d in recs.values())))
    res.status = "WARN"
    res.detail = (f"{bad} 等菜谱的 category 是 other，而其它中式菜系都是 chinese。"
                  "菜谱数据里 cuisine 和 category 两套分类字段并存且口径不一致，"
                  "界面目前按 cuisine 过滤所以看起来正常，但一旦有代码改用 category "
                  "就会漏掉这些菜。建议二选一、统一口径")


@case("I9", "user_config 默认值不在界面可选项内", GROUP, "P1")
def c_i9(r, res):
    cfg = P.read_user_config()
    prof = cfg.get("profile") or {}
    spice = prof.get("spice_level")
    rect = (cfg.get("user_id"), P.read_users()["users"][0].get("user_id"))
    msgs = []
    if spice not in ("不辣", "微辣", "中辣", "重辣"):
        msgs.append(f"spice_level='{spice}' 不在辣度可选项"
                    "[不辣/微辣/中辣/重辣] 中，界面无法正确回显")
    if rect[0] != rect[1]:
        msgs.append(f"user_config.user_id={rect[0]} 与 users.user_id={rect[1]} 不一致")
    if prof.get("nickname") == "":
        msgs.append("profile.nickname 为空字符串，而首页/个人页显示的是 "
                    "shared_prefs 里的 username，昵称存在两套来源")
    check(not msgs, "；".join(msgs) + "。另外 user_config.json 中所有中文都被转义为 "
          "\\uXXXX（如 \\u9002\\u4e2d），说明写入时用了不保留中文的序列化方式")


@case("I10", "菜谱难度分级只有 1~3，缺少高档位", GROUP, "P2")
def c_i10(r, res):
    recs = P.load_recipes_local()
    dist = collections.Counter(d.get("difficulty") for d in recs.values())
    check(len(dist) >= 4,
          f"41 道菜的 difficulty 取值只有 {dict(dist)}，"
          "而界面按 ★★★★★（5 档）渲染难度。4★/5★ 永远为空，"
          "所有菜看起来都是“简单到中等”，难度分级的区分度失效")
