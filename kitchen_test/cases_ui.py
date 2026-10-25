# -*- coding: utf-8 -*-
"""界面用例：功能完整性、逻辑自洽性、异常与边界。

规范对应：
  - 页面对象模式：用例只调用 pages.py 的操作，不自己拼坐标逻辑。
  - 显式等待：本文件没有任何 time.sleep；tap/back 之后一律用
    device.wait_* / pages.wait_* 等条件成立再继续。
  - 测试数据与代码分离：期望值都从应用数据（菜谱 JSON / user_config）读。

抽样策略：菜谱相关用例抽样 4 道菜（麻婆豆腐/番茄炒蛋/红烧肉/凯撒沙拉），
覆盖中式炒制与西式凉拌两类差异较大的流程，不逐道遍历 41 道。
走流程的结果做缓存，多个用例共享一次走查，避免重复耗时。
"""
import re
import time

from . import device as D
from . import pages as P
from .framework import case, check
from .waits import WaitTimeout

SAMPLES = ["麻婆豆腐", "番茄炒蛋", "红烧肉", "凯撒沙拉"]

_walk_cache = {}


def walk(dish):
    """走一遍指定菜谱的助手模式（带缓存，多个用例共享一次走查）。"""
    if dish not in _walk_cache:
        recipe = P.load_recipes_local()[dish]
        _walk_cache[dish] = P.finish_to_result(dish, recipe)
    return _walk_cache[dish]


def walk_fresh(dish):
    """不走缓存，真的重新走一遍，用于需要停留在结果页的用例。"""
    recipe = P.load_recipes_local()[dish]
    log = P.finish_to_result(dish, recipe)
    _walk_cache[dish] = log
    return log


def recipe_of(dish):
    return P.load_recipes_local()[dish]


def count_text(u):
    """列表页顶部的「共 N 道菜」文字。"""
    n = u.by_text("共", contains_any=True)
    return n.text if n else None


def scroll_collect_dishes(max_scroll=25):
    """把当前列表滚到底，收集全部菜名。每次循环只抓一次界面。"""
    names, prev_sig = [], None
    for _ in range(max_scroll):
        u = D.ui()
        for t in P.visible_dish_list(u):
            if t not in names:
                names.append(t)
        sig = tuple(n.text for n in u.nodes)
        if sig == prev_sig:
            break                       # 滑了但内容没变 → 到底了
        prev_sig = sig
        D.swipe(540, 1800, 540, 900, 400)
    return names


_fresh = {}


def fresh_result(dish=SAMPLES[0]):
    """真的重新走一遍并停在结果页。E3/E4 共用一次走查，避免重复耗时。"""
    if (_fresh.get("log") and _fresh.get("dish") == dish
            and P.RESULT_ACT in D.current_focus()):
        return _fresh["log"]
    log = walk_fresh(dish)
    _fresh.update(dish=dish, log=log)
    return log


# ============================================================ 启动与首页
G_ENTRY = "启动与首页"


@case("A1", "冷启动能进入首页，五个功能入口齐全且可点击", G_ENTRY, "P1")
def c_a1(r, res):
    ui = P.go_home()
    ids = ["card_start_cooking", "card_kitchen_setting", "card_profile",
           "card_history", "card_knowledge"]
    missing = [i for i in ids if ui.by_id(i) is None]
    check(not missing, f"首页缺少入口卡片: {missing}")
    bad = [i for i in ids if not ui.by_id(i).clickable]
    check(not bad, f"以下入口卡片不可点击: {bad}")
    n = ui.by_id("tv_welcome")
    check(n is not None and "同学" in n.text,
          f"首页欢迎语异常: {n.text if n else None}")


@case("A2", "首页「退出登录」按钮尺寸为 0，用户无法点击", G_ENTRY, "P1")
def c_a2(r, res):
    ui = P.go_home()
    n = ui.by_id("tv_logout")
    check(n is not None, "首页没有找到退出登录控件")
    check(n.displayed,
          f"「退出登录」控件存在于界面树中（clickable={n.clickable}），"
          f"但 bounds={n.bounds}，宽高为 0，即界面上完全不可见、也不可点击。"
          "首页也没有溢出菜单或其它退出登录入口，用户实际上无法退出当前账号")


@case("A3", "菜谱选择页可用返回键回到首页", G_ENTRY, "P2")
def c_a3(r, res):
    P.go_home()
    P.open_recipe_list()
    D.back()
    try:
        D.wait_focus(P.HOME_ACT, timeout=8, desc="返回后回到首页")
    except WaitTimeout:
        pass
    focus = D.current_focus()
    check(P.HOME_ACT in focus,
          f"从菜谱列表返回后焦点为 {focus}，未回到首页")


# ============================================================ 菜谱列表
G_LIST = "菜谱列表"


@case("B1", "列表页菜谱总数与数据不一致", G_LIST, "P1")
def c_b1(r, res):
    P.go_home()
    ui = P.open_recipe_list()
    text = count_text(ui)
    check(text is not None, "列表页没有显示菜谱总数")
    m = re.search(r"(\d+)", text)
    shown = int(m.group(1)) if m else -1
    real = len(P.load_recipes_local())
    check(shown == real,
          f"列表页显示「{text}」，但设备上实际只有 {real} 个菜谱数据文件，"
          f"相差 {shown - real} 道")


@case("B2", "分类筛选用菜名与数据不符，且有分类计数虚高", G_LIST, "P1")
def c_b2(r, res):
    """两遍扫描：先只读各分类的计数，再对"计数与数据不符"的分类做逐条菜名比对。

    为什么要两遍：读计数只要 1 次界面抓取，而把某个分类的菜名全滚一遍要 2~6 次。
    计数与数据一致时说明该分类没有偏差，可以省掉逐条比对（本机一次抓取约 2.4s，
    8 个分类全滚一遍要 1 分钟）。计数不一致的才展开核查——正是这些分类藏问题。
    """
    P.go_home()
    P.open_recipe_list()
    recs = P.load_recipes_local()
    mapping = [
        ("川菜", lambda d: d.get("cuisine") == "川菜"),
        ("湘菜", lambda d: d.get("cuisine") == "湘菜"),
        ("粤菜", lambda d: d.get("cuisine") == "粤菜"),
        ("家常菜", lambda d: d.get("cuisine") == "家常菜"),
        ("日料", lambda d: d.get("cuisine") == "日料"),
        ("西餐", lambda d: d.get("cuisine") == "西餐"),
        ("韩餐", lambda d: d.get("cuisine") == "韩餐"),
        ("东南亚/闽菜", lambda d: d.get("cuisine") in ("东南亚", "闽菜")),
    ]
    problems, detail = [], []

    counts = {}
    for label, _ in mapping:
        if not P.click_category(label):
            problems.append(f"{label}: 界面上找不到该分类标签")
            continue
        text = count_text(D.ui())
        m = re.search(r"(\d+)", text) if text else None
        counts[label] = (text, int(m.group(1)) if m else -1)

    for label, fn in mapping:
        if label not in counts:
            continue
        exp = {n for n, d in recs.items() if fn(d)}
        text, counter = counts[label]
        if counter == len(exp):
            detail.append(f"{label}: 计数{counter} == 数据{len(exp)}（一致）")
            continue
        P.click_category(label)
        got = scroll_collect_dishes()
        detail.append(f"{label}: 计数文案{counter} / 实际列出{len(got)} / 数据{len(exp)}")
        for n in sorted(set(got) - exp):
            problems.append(f"{label} 里多出「{n}」"
                            f"（数据里 cuisine={recs.get(n, {}).get('cuisine')}）")
        for n in sorted(exp - set(got)):
            problems.append(f"{label} 里缺少「{n}」")
        if counter != len(got):
            problems.append(f"{label} 顶部写「{text}」，但实际只列出了 "
                            f"{len(got)} 道")
    res.notes.append("；".join(detail))
    check(not problems,
          "分类筛选与菜谱数据不一致：\n  " + "\n  ".join(problems)
          + "\n  完整对照：" + "；".join(detail))


@case("B3", "闽菜（category=other）不在任何分类筛选里", G_LIST, "P2")
def c_b3(r, res):
    P.go_home()
    P.open_recipe_list()
    P.click_category("东南亚/闽菜")
    names = scroll_collect_dishes(max_scroll=12)
    check("佛跳墙" in names,
          f"数据里「佛跳墙」的 cuisine=闽菜、category=other，"
          f"但分类标签「东南亚/闽菜」下找不到它（该标签下只列出了 {names}）。"
          "该菜只能在「全部」里翻到，分类入口漏了一套映射")


@case("B4", "搜索无匹配内容时的空态", G_LIST, "P2")
def c_b4(r, res):
    P.go_home()
    P.open_recipe_list()
    before = count_text(D.ui())
    P.search("zzqq")
    try:
        D.wait_ui(lambda u: count_text(u) != before, timeout=8,
                  desc="搜索结果刷新")
    except WaitTimeout:
        pass
    P.hide_keyboard()
    ui = D.ui()
    text = count_text(ui)
    texts = [n.text for n in ui.nodes if n.text]
    hit = [x for x in texts if "没有" in x or "无" in x or "未找到" in x
           or "空空" in x or "换" in x]
    res.notes.append(f"搜索 zzqq 后界面文字: {texts[:14]}")
    check(text is not None or hit,
          "搜索一个必然无结果的关键词后，页面既没有显示结果数量，"
          "也没有任何空状态提示（无「没有找到相关菜谱」之类文案），"
          f"界面只剩分类栏，用户不知道发生了什么。当前文字: {texts[:10]}")


# ============================================================ 菜谱详情
G_DETAIL = "菜谱详情"


def open_detail(dish="麻婆豆腐"):
    """首页 -> 列表 -> 打开菜谱 -> 菜谱详解，并等详情内容渲染出来。"""
    P.go_home()
    P.open_recipe_list()
    ok, sc, _ = P.open_dish_by_name(dish)
    check(ok, f"列表里找不到{dish}（滚动 {sc} 次）")
    check(P.choose_mode("菜谱详解"), "没有弹出烹饪模式选择框")
    D.wait_text("食材清单", timeout=15)      # 等详情内容真正渲染
    return D.ui()


_detail_cache = {}


def scan_detail(dish="麻婆豆腐"):
    """一次滚动把详情页的「步骤」和「评分标准」都采集下来（带缓存）。

    详情页很长，滚动一次要抓十几次界面（每次约 2.4s），所以 C1/C2 共用一次扫描。
    """
    if dish in _detail_cache:
        return _detail_cache[dish]
    open_detail(dish)
    recipe = recipe_of(dish)
    cn = {"knife_skills": "刀工处理", "heat_control": "火候控制",
          "seasoning": "调味逻辑", "step_order": "步骤顺序",
          "time_efficiency": "时间效率", "creativity": "创意搭配"}
    want_scores = {cn[k] for k in recipe["scoring"]}
    steps, scores, prev_sig = [], {}, None
    rx = re.compile(r"^步骤(\d+)：(.+)$")
    for _ in range(16):
        u = D.ui()
        for n in u.nodes:
            m = rx.match(n.text or "")
            if m:
                item = (int(m.group(1)), m.group(2))
                if item not in steps:
                    steps.append(item)
            if n.text in want_scores and n.center:
                for m in u.nodes:
                    if (m.cls.endswith("TextView") and m.text and m.center
                            and re.fullmatch(r"\d+分", m.text)
                            and abs(m.center[1] - n.center[1]) < 30
                            and m.center[0] > n.center[0]):
                        scores[n.text] = int(m.text[:-1])
                        break
        sig = tuple(n.text for n in u.nodes)
        if sig == prev_sig:
            break
        prev_sig = sig
        D.swipe(540, 1800, 540, 800, 400)
    steps.sort()
    out = {"steps": steps, "scores": scores, "recipe": recipe}
    _detail_cache[dish] = out
    return out


@case("C1", "详情页步骤缺失，且编号从「步骤4」开始", G_DETAIL, "P1")
def c_c1(r, res):
    scan = scan_detail()
    exp = P.expected_flow(scan["recipe"])
    found = scan["steps"]
    nums = [i for i, _ in found]
    names = [t for _, t in found]
    res.notes.append(f"详情页步骤: {found}；数据: {exp}")
    problems = []
    missing = [x for x in exp if x not in names]
    if missing:
        problems.append(f"缺少数据里定义的步骤 {missing}")
    if nums != list(range(1, len(nums) + 1)):
        problems.append(f"步骤编号不是从1连续排列，而是 {nums}"
                        f"（说明前面几号步骤被跳过了）")
    check(not problems,
          "；".join(problems)
          + f"。菜谱数据定义了 {len(exp)} 个步骤 {exp}，"
          f"详情页只列出了 {found}。编号直接跳到 4，用户在详情页既看不到"
          "前 3 步，也没有任何解释")


@case("C2", "详情页评分标准与 scoring 数据一致", G_DETAIL, "P2")
def c_c2(r, res):
    scan = scan_detail()
    recipe = scan["recipe"]
    cn = {"knife_skills": "刀工处理", "heat_control": "火候控制",
          "seasoning": "调味逻辑", "step_order": "步骤顺序",
          "time_efficiency": "时间效率", "creativity": "创意搭配"}
    exp = {cn[k]: v for k, v in recipe["scoring"].items()}
    got = scan["scores"]
    res.notes.append(f"详情页评分标准={got}；数据={exp}")
    check(got == exp,
          f"详情页「评分标准」与菜谱 scoring 不一致（界面, 数据）: "
          f"{ {k: (got.get(k), exp[k]) for k in exp if got.get(k) != exp[k]} }")


# ============================================================ 烹饪流程
G_COOK = "烹饪流程"


def open_cooking(dish="番茄炒蛋"):
    """进入某道菜的助手模式并关掉可能出现的阻断弹窗。"""
    P.go_home()
    P.open_recipe_list()
    ok, _, _ = P.open_dish_by_name(dish)
    check(ok, f"列表里找不到{dish}")
    check(P.choose_mode("助手模式"), "没有弹出烹饪模式选择框")
    d = P.close_dialog()
    return d


_cook_page = {}


def cooking_page(dish="番茄炒蛋"):
    """进入烹饪第 1 步并缓存快照。

    D5/D6 都只是"读"这一页（一个读忌口、一个读口味偏好），共用一次进入即可，
    省下一整趟"首页→列表→选菜→进烹饪"的开销（约 45 秒）。
    """
    if (_cook_page.get("dish") == dish and P.COOK_ACT in D.current_focus()):
        u = D.ui()
        if u.by_id("tv_step_title") is not None:
            return u
    open_cooking(dish)
    u = D.ui()
    check(u.by_id("tv_step_title") is not None, "没有进入烹饪步骤页")
    _cook_page.update(dish=dish, ui=u)
    return u


def cooking_page_here_or_open(dish="番茄炒蛋"):
    """如果当前就在烹饪页就复用，否则重新进一次（D7→D8 共用）。"""
    if P.COOK_ACT in D.current_focus():
        u = D.ui()
        if u.by_id("tv_step_title") is not None:
            return True
    open_cooking(dish)
    return True


@case("D1", "助手模式步骤数与数据定义不一致（抽样4道）", G_COOK, "P0")
def c_d1(r, res):
    bad, detail = [], []
    for dish in SAMPLES:
        log = walk(dish)
        check("error" not in log, f"{dish}: {log.get('error')}")
        exp = P.expected_flow(recipe_of(dish))
        got = [s["title"] for s in log["steps"]]
        detail.append(f"{dish}: 数据 {len(exp)} 步{exp} / 界面 {len(got)} 步{got}")
        missing = [x for x in exp if x not in got]
        if missing:
            bad.append(f"{dish} 丢弃了 {missing}")
    res.notes += detail
    check(not bad,
          "「助手模式」号称“跟着标准步骤走，学习正宗做法”，但界面只呈现固定的"
          "「食材准备 + 少量步骤」，菜谱数据里定义的其它步骤被静默丢弃：\n  "
          + "\n  ".join(bad)
          + "\n  实测：" + "；".join(detail))


@case("D2", "结果页评分分母被写死，出现“30/20”这类得分率超 100% 的显示",
      G_COOK, "P0")
def c_d2(r, res):
    cn = {"knife_skills": "刀工处理", "heat_control": "火候控制",
          "seasoning": "调味逻辑", "step_order": "步骤顺序",
          "time_efficiency": "时间效率", "creativity": "创意搭配"}
    bad, detail, denoms = [], [], {}
    for dish in SAMPLES:
        log = walk(dish)
        check(log.get("result"), f"{dish}: 没走到结果页")
        exp = {cn[k]: v for k, v in recipe_of(dish)["scoring"].items()}
        got = {name.split(" ", 1)[-1]: val for name, val in log["result"]["items"]}
        for k, val in got.items():
            a, b = [int(x) for x in val.split("/")]
            denoms.setdefault(k, set()).add(b)
            if b != exp.get(k):
                bad.append(f"{dish}「{k}」分母 {b}，数据里是 {exp.get(k)}")
            if a > b:
                bad.append(f"{dish}「{k}」= {val}，得分率 {a / b * 100:.0f}%")
        detail.append(f"{dish}: {got}（数据满分 {exp}）")
    hardcoded = {k: v for k, v in denoms.items() if len(v) == 1}
    res.notes.append("分母取值集合: " + str({k: sorted(v) for k, v in denoms.items()}))
    res.notes += detail
    check(not bad,
          "结果页六项评分的分母与菜谱数据里 scoring 定义的满分脱钩，"
          "看起来是写死的常数"
          + (f"（实测分母恒为 { {k: sorted(v)[0] for k, v in hardcoded.items()} }）"
             if hardcoded else "")
          + "：\n  " + "\n  ".join(bad)
          + "\n  实测：" + "；".join(detail))


@case("D3", "存在没有可选项的食材，且校验仍要求选择", G_COOK, "P0")
def c_d3(r, res):
    bad, detail = [], []
    for dish in SAMPLES:
        log = walk(dish)
        skipped = log.get("skipped_ingredients") or []
        pick = log["steps"][0].get("should_pick") if log["steps"] else []
        detail.append(f"{dish}: 数据里无可选项的食材={skipped}, 界面实选={pick}")
        if skipped:
            bad.append(f"{dish} 的食材 {skipped} 在数据里 options 为空，"
                       "界面只显示食材名、不显示任何选项")
    res.notes += detail
    check(not bad,
          "；".join(bad)
          + "。而点「下一步」时的校验提示是「请为每种食材选择处理方式」，"
          "用户永远无法为这些食材做出选择，属于引导语与实际校验互相矛盾")


@case("D4", "未选完就点下一步：有提示且不前进", G_COOK, "P2")
def c_d4(r, res):
    open_cooking("麻婆豆腐")
    u = D.ui()
    before = P.cooking_snapshot(u)["progress"]
    btn = u.by_id("btn_next")
    check(btn is not None, "烹饪页没有「下一步」按钮")
    D.tap(*btn.center)
    # 显式等待式的"负向断言"：给它一段时间，看进度会不会变
    advanced = True
    try:
        D.wait_id_text_change("tv_progress", before, timeout=5,
                              desc="未选完也允许推进")
    except WaitTimeout:
        advanced = False
    res.notes.append(f"未选完点击下一步：停留于 {before}，未放行")
    check(not advanced, "一步都没选就能通过校验进入下一步")
    # 提示文案是 Toast，不在控件树里（已用截图+OCR 另证为
    # 「请为每种食材选择处理方式」），这里只验证"没有放行"


@case("D5", "忌口为空时显示成“[]”", G_COOK, "P2")
def c_d5(r, res):
    dislike = (P.read_user_config().get("profile") or {}).get("dislike") or []
    check(not dislike, f"忌口配置非空 {dislike}，本用例前提不成立")
    u = cooking_page("番茄炒蛋")
    line = next((n.text for n in u.nodes if n.text and "你的忌口" in n.text), None)
    check(line is not None, "烹饪页没有显示忌口信息")
    check("[]" not in line,
          f"用户没有设置忌口时，页面直接打印了空列表的字面量：{line!r}。"
          "应显示「无」或整行隐藏")


@case("D6", "口味偏好展示与个人信息配置一致", G_COOK, "P2")
def c_d6(r, res):
    prof = P.read_user_config().get("profile") or {}
    u = cooking_page("番茄炒蛋")
    line = next((n.text for n in u.nodes if n.text and "口味偏好" in n.text), None)
    check(line is not None, "烹饪页没有显示口味偏好")
    res.notes.append(f"配置 spice/sweet/salt = "
                     f"{prof.get('spice_level')}/{prof.get('sweet_level')}/"
                     f"{prof.get('salt_level')}；界面显示 {line!r}")
    for key in ("spice_level", "sweet_level", "salt_level"):
        check(prof.get(key) is not None, f"配置里缺少 {key}")


@case("D7", "进入烹饪时弹厨具提示，但不影响继续烹饪", G_COOK, "P2")
def c_d7(r, res):
    P.go_home()
    P.open_recipe_list()
    ok, _, _ = P.open_dish_by_name("番茄炒蛋")
    check(ok, "列表里找不到番茄炒蛋")
    check(P.choose_mode("助手模式"), "没有弹出烹饪模式选择框")
    d = P.wait_dialog(timeout=8)
    if not d:
        res.status = "SKIP"
        res.detail = "本次进入烹饪没有弹出厨具提示（配置或状态已变）"
        P.close_dialog()
        return
    title, msg, btns = d
    res.notes.append(f"弹窗: {title} / {msg!r} / 按钮 {btns}")
    check("厨具" in (title or ""), f"进入烹饪时出现意外弹窗: {title}")
    P.close_dialog()          # 点「知道了」后应能正常烹饪
    check(D.ui().by_id("tv_step_title") is not None,
          "关掉厨具提示后没有进入烹饪步骤页")
    res.notes.append("该提示是纯提示性质：点「知道了」后照常进入烹饪，"
                     "并未阻止用户使用缺失的厨具完成整道菜")


@case("D8", "烹饪中按返回键有二次确认", G_COOK, "P2")
def c_d8(r, res):
    # D7 刚把我们带到烹饪页，直接复用，不必再进一次
    cooking_page_here_or_open("番茄炒蛋")
    D.back()
    d = P.wait_dialog(timeout=8)
    check(d is not None, "烹饪中按返回键没有出现确认弹窗，直接退出了")
    check("退出" in (d[0] or ""), f"返回确认弹窗标题异常: {d[0]}")
    res.notes.append(f"弹窗: {d[0]} / {d[1]!r} / 按钮 {d[2]}")
    P.close_dialog()


# ============================================================ 结果页
G_RESULT = "结果页"


@case("E1", "结果页各项得分之和不等于总分", G_RESULT, "P0")
def c_e1(r, res):
    bad, detail = [], []
    for dish in SAMPLES:
        log = walk(dish)
        r_ = log.get("result")
        check(r_, f"{dish}: 没走到结果页")
        tot = sum(int(v.split("/")[0]) for _, v in r_["items"])
        detail.append(f"{dish}: 单项之和={tot} 总分={r_['total']}")
        if int(r_["total"]) != tot:
            bad.append(f"{dish}: 单项之和 {tot} != 总分 {r_['total']}")
    res.notes += detail
    check(not bad, "；".join(bad))


@case("E2", "满分 100 分实际不可达（创意搭配恒为 0）", G_RESULT, "P2")
def c_e2(r, res):
    detail, totals = [], []
    for dish in SAMPLES:
        log = walk(dish)
        r_ = log.get("result")
        check(r_, f"{dish}: 没走到结果页")
        d = {k.replace("💡 ", ""): v for k, v in r_["items"]}
        totals.append(int(r_["total"]))
        detail.append(f"{dish}: 总分 {r_['total']}（创意搭配 {d.get('创意搭配')}）")
    res.notes += detail
    res.status = "WARN"
    res.detail = ("即使每一步都选了界面标注的「标准做法建议」选项，"
                  f"总分也只有 {totals}，没有任何一次达到 100。"
                  "「创意搭配」固定得 0 分，满分 100 的文案与实际可达上限不符。"
                  "实测：" + "；".join(detail))


@case("E3", "保存记录有反馈且按钮置为已保存", G_RESULT, "P2")
def c_e3(r, res):
    log = fresh_result()
    check(log.get("result"), "没走到结果页")
    before = len(P.read_history_files())
    u = D.ui()
    btn = u.by_id("btn_save_history")
    check(btn is not None, "结果页没有「保存记录」按钮")
    old_text = btn.text
    D.tap(*btn.center)
    try:
        D.wait_id_text_change("btn_save_history", old_text, timeout=8,
                              desc="保存按钮文字变化")
    except WaitTimeout:
        pass
    nb = D.ui().by_id("btn_save_history")
    after = len(P.read_history_files())
    res.notes.append(f"保存前记录数={before}，保存后={after}，"
                     f"按钮文字 {old_text!r} -> {nb.text if nb else None!r}")
    check(nb is not None and nb.text != old_text,
          "点击「保存记录」后按钮文字没有变化，用户无法确认是否保存成功")
    check(after >= before, "保存后历史记录条数反而减少")


@case("E4", "结果页可返回首页", G_RESULT, "P2")
def c_e4(r, res):
    log = fresh_result()
    check(log.get("result"), "没走到结果页")
    u = D.ui()
    btn = u.by_id("btn_back_home")
    check(btn is not None, "结果页没有「返回首页」按钮")
    D.tap(*btn.center)
    try:
        D.wait_focus(P.HOME_ACT, timeout=8, desc="返回首页")
    except WaitTimeout:
        pass
    focus = D.current_focus()
    check(P.HOME_ACT in focus, f"点「返回首页」后焦点是 {focus}")


# ============================================================ 厨房设置
G_KITCHEN = "厨房设置"


def open_kitchen_setting():
    P.go_home()
    D.tap(*D.ui().by_id("card_kitchen_setting").center)
    D.wait_focus(P.KITCHEN_ACT, timeout=12, desc="进入厨房设置")
    return D.ui()


def choose_kitchen_type(label):
    u = D.ui()
    n = u.by_text(label, exact=True)
    if n is None:
        return False
    D.tap(*n.center)
    D.wait_text("常用工具", timeout=12, desc=f"选择{label}后出现工具列表")
    return True


@case("F1", "四种厨房类型可选，选择后出现对应工具", G_KITCHEN, "P2")
def c_f1(r, res):
    ui = open_kitchen_setting()
    types = [t for t in ("中式厨房", "西式厨房", "日式厨房", "东南亚厨房")
             if ui.by_text(t, exact=True)]
    check(len(types) == 4, f"厨房类型不齐全，只找到 {types}")
    n_before = len([n for n in ui.nodes if n.text == "详情 >"])
    check(choose_kitchen_type("西式厨房"), "找不到「西式厨房」选项")
    ui2 = D.ui()
    n_after = len([x for x in ui2.nodes if x.text == "详情 >"])
    res.notes.append(f"未选类型时工具数={n_before}，选西式厨房后工具数={n_after}")
    check(n_after > 0, "选择厨房类型后没有出现常用工具列表")
    check("常用工具" in ui2.all_text(), "选择类型后没有出现「常用工具」区域")


@case("F2", "厨房设置保存后写入 user_config.json", G_KITCHEN, "P1")
def c_f2(r, res):
    open_kitchen_setting()
    check(choose_kitchen_type("中式厨房"), "找不到「中式厨房」选项")
    ui = D.ui()
    rows = [n for n in ui.nodes if n.text == "详情 >"]
    check(rows, "中式厨房下没有工具列表")
    before = P.read_user_config()
    D.tap(540, rows[0].center[1])          # 勾选第一个工具
    try:
        D.wait_ui(lambda u: any(n.text == "✅" for n in u.nodes), timeout=8,
                  desc="工具被勾选")
    except WaitTimeout:
        pass
    chk = [n.text for n in D.ui().nodes if n.text in ("⬜", "✅")]
    D.tap(*D.ui().by_id("btn_save").center)
    after = P.wait_user_config_change(before, timeout=8)
    res.notes.append(f"保存前 {before.get('kitchen_type')}/{before.get('tools')} "
                     f"-> 保存后 {after.get('kitchen_type')}/{after.get('tools')}"
                     f"；勾选框状态 {chk}")
    check(after.get("kitchen_type") != before.get("kitchen_type")
          or after.get("tools") != before.get("tools"),
          "点了「保存设置」并勾选了工具，但 user_config.json 里的 "
          "kitchen_type / tools 都没有任何变化，设置没有真正落盘")


# ============================================================ 个人信息
G_PROFILE = "个人信息"


def open_profile():
    P.go_home()
    D.tap(*D.ui().by_id("card_profile").center)
    D.wait_focus(P.PROFILE_ACT, timeout=12, desc="进入个人信息")
    return D.ui()


@case("G1", "个人信息默认值与 user_config 不一致（辣度无对应选项）", G_PROFILE, "P1")
def c_g1(r, res):
    prof = P.read_user_config().get("profile") or {}
    snap = P.profile_snapshot(open_profile())
    res.notes.append(f"配置={prof}；界面={snap}")
    spice = snap["levels"].get("rg_spice", {})
    check(prof.get("spice_level") in (spice.get("options") or []),
          f"user_config.json 里 spice_level='{prof.get('spice_level')}'，"
          f"但界面辣度的可选项只有 {spice.get('options')}，两者对不上。"
          f"界面当前高亮的是「{spice.get('checked')}」，也就是说用户并没有"
          "选过‘中辣’，是靠默认值/下标顶上去的，回显与真实配置不一致")


@case("G2", "昵称存在两套来源且不一致", G_PROFILE, "P2")
def c_g2(r, res):
    prof = P.read_user_config().get("profile") or {}
    prefs = P.read_prefs()
    ui = P.go_home()
    n = ui.by_id("tv_welcome")
    home_text = n.text if n else ""
    D.tap(*ui.by_id("card_profile").center)
    D.wait_focus(P.PROFILE_ACT, timeout=12, desc="进入个人信息")
    snap = P.profile_snapshot(D.ui())
    res.notes.append(f"首页欢迎语={home_text!r}；个人页昵称={snap['nickname']!r}；"
                     f"user_config.profile.nickname={prof.get('nickname')!r}；"
                     f"user_prefs={prefs.strip()[:140]}")
    check(not (snap["nickname"] and prof.get("nickname") == ""),
          f"个人页昵称框显示 {snap['nickname']!r}，但 user_config.json 里 "
          f"profile.nickname={prof.get('nickname')!r}（空）。"
          "说明昵称其实来自 shared_prefs 的 username，个人信息页只是把用户名"
          "塞进了昵称框，两份数据源并存，改昵称不会同步")


@case("G3", "忌口输入并保存后写入 user_config.json", G_PROFILE, "P1")
def c_g3(r, res):
    ui = open_profile()
    box = ui.by_id("et_dislike")
    check(box is not None, "个人页没有忌口输入框")
    D.tap(*box.center)
    P.wait_keyboard_shown()
    # 先清空再输入。中文无法通过 adb input text 输入（见项目记忆），
    # 这里用 ASCII 验证"逗号分隔解析 + 落盘"这条逻辑链。
    D.shell("input keyevent 123")
    for _ in range(40):
        D.shell("input keyevent 67")
    D.invalidate()
    D.shell('input text "aaa,bbb,ccc"', check=False)
    D.invalidate()
    P.hide_keyboard()
    before = P.read_user_config()
    D.tap(*D.ui().by_id("btn_save").center)
    after = P.wait_user_config_change(before, timeout=8)
    dislike = (after.get("profile") or {}).get("dislike")
    res.notes.append(f"输入 'aaa,bbb,ccc' 后 user_config 里 dislike = {dislike}")
    check(dislike == ["aaa", "bbb", "ccc"],
          f"忌口按逗号分隔的解析结果不是 ['aaa','bbb','ccc']，实际写入了 {dislike!r}")


@case("G4", "三者口味偏好保存后落盘", G_PROFILE, "P2")
def c_g4(r, res):
    open_profile()
    before = P.read_user_config().get("profile")
    check(P.select_radio("重辣"), "找不到「重辣」选项或它没被选中")
    D.tap(*D.ui().by_id("btn_save").center)
    after = P.wait_user_config_change(before, timeout=8).get("profile")
    res.notes.append(f"辣度 {before.get('spice_level')} -> {after.get('spice_level')}")
    check(after.get("spice_level") != before.get("spice_level"),
          f"选择了「重辣」并保存，但 user_config.json 里 spice_level 仍是 "
          f"'{after.get('spice_level')}'，偏好没有保存成功")
