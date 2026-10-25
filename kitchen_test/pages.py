# -*- coding: utf-8 -*-
"""页面对象（Page Object）层 + 应用数据读取。

规范对应关系：
  - 「强制用页面对象模式封装元素」→ 用例不直接碰坐标/元素，只用这里的函数。
  - 「优先用 data 属性定位」→ 优先 by_id(resource-id)，取不到才退回文本定位。
  - 「禁止硬等待，必须用显式等待」→ 本文件没有任何 time.sleep，等待一律走
    device.wait_* / waits.until，条件成立立刻返回。
  - 「测试数据与代码分离」→ 期望值都从应用数据文件读（read_* / load_recipes_local），
    用例里不写死。

性能要点：本机一次界面抓取约 2.4 秒，所以刻意做了两件事：
  (1) 同一"无输入间隔"内复用同一张界面快照（device.ui() 带缓存）；
  (2) 点选选项时按数据顺序在**同一张快照**上连续命中，而不是每点一次重抓一次。
"""
import os
import re
import json
import time
import subprocess

from . import device as D

PKG = "com.example.kitchenassistant"
HOME_ACT = "HomeActivity"
LIST_ACT = "RecipeSelectActivity"
COOK_ACT = "CookingActivity"
DETAIL_ACT = "RecipeDetailActivity"
RESULT_ACT = "ResultActivity"
PROFILE_ACT = "ProfileActivity"
KITCHEN_ACT = "KitchenSettingActivity"

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJ, "data_dump", "appdata")


# ================================================================ 应用数据
def _cat(rel):
    p = subprocess.run(["adb", "exec-out", "run-as", PKG, "cat", f"files/data/{rel}"],
                       capture_output=True)
    return p.stdout.decode("utf-8", "replace")


def read_user_config():
    return json.loads(_cat("user_config.json"))


def read_users():
    return json.loads(_cat("users.json"))


def read_prefs():
    return _cat("../../shared_prefs/user_prefs.xml")


def read_history_files():
    out = subprocess.run(
        ["adb", "shell", "run-as", PKG, "sh", "-c", "'ls files/data/history'"],
        capture_output=True)
    return [l.strip() for l in out.stdout.decode("utf-8", "replace").splitlines()
            if l.strip().endswith(".json")]


def write_user_config(text):
    """把 user_config.json 写回设备（用于测试后恢复现场）。"""
    cmd = f"run-as {PKG} sh -c 'cat > files/data/user_config.json'"
    p = subprocess.run(["adb", "shell", cmd],
                       input=text.encode("utf-8"), capture_output=True)
    return p.returncode == 0


def backup_user_config():
    return _cat("user_config.json")


def restore_user_config(text):
    return write_user_config(text)


def load_recipes_local():
    """从本地已导出的数据里读菜谱（离线核对用）。"""
    out = {}
    rd = os.path.join(DATA_DIR, "recipes")
    if not os.path.isdir(rd):
        return out
    for f in sorted(os.listdir(rd)):
        if f.endswith(".json"):
            with open(os.path.join(rd, f), encoding="utf-8") as fh:
                out[f[:-5]] = json.load(fh)
    return out


# ================================================================ 界面元素
def option_name(u, radio):
    """某个 RadioButton 对应的选项名（同行右侧最近的文字）。"""
    best = None
    for n in u.nodes:
        if not (n.cls.endswith("TextView") and n.text and n.center):
            continue
        if n.center[0] <= radio.center[0]:
            continue
        if abs(n.center[1] - radio.center[1]) < 30:
            if best is None or n.center[0] < best.center[0]:
                best = n
    return best.text if best else None


def option_groups(u):
    """把可见的 RadioButton 按分组切分（同组纵向间距 < 200px）。"""
    radios = sorted([n for n in u.nodes
                     if n.cls.endswith("RadioButton") and n.center],
                    key=lambda n: n.center[1])
    groups = []
    for r in radios:
        if groups and r.center[1] - groups[-1][-1].center[1] < 200:
            groups[-1].append(r)
        else:
            groups.append([r])
    return groups


def option_rows(u):
    """可点击的选项行（高 > 100px 的 FrameLayout），用于"有没有选项"的判断。"""
    return [n for n in u.nodes
            if n.clickable and n.cls.endswith("FrameLayout") and n.center
            and n.bounds and (n.bounds[3] - n.bounds[1]) > 100]


def group_label(u, first_radio):
    """分组标题（第一个选项上方最近的文字）。"""
    best = None
    for n in u.nodes:
        if not (n.cls.endswith("TextView") and n.text and n.center):
            continue
        dy = first_radio.center[1] - n.center[1]
        if 0 < dy < 140 and (best is None or n.center[1] > best.center[1]):
            best = n
    return best.text if best else None


def _find_option_node(u, name):
    """在快照里找某个选项名（只认选项区，排除顶部标题区）。"""
    for n in u.nodes:
        if n.text == name and n.center and n.center[1] > 400:
            return n
    return None


def _visible_signature(u):
    return tuple(n.text for n in u.nodes if n.text)


def step_option_names(u):
    return [nm for g in option_groups(u) for nm in
            (option_name(u, r) for r in g) if nm]


def step_selected_names(u):
    return [nm for g in option_groups(u) for r in g if r.checked
            for nm in (option_name(u, r),) if nm]


def cooking_snapshot(u):
    """抽取烹饪页关键状态。"""
    def txt(i):
        n = u.by_id(i)
        return n.text if n else None
    return {
        "step_title": txt("tv_step_title"),
        "progress": txt("tv_progress"),
        "timer": txt("tv_timer"),
        "desc": txt("tv_step_description"),
        "next": txt("btn_next"),
        "prev": txt("btn_prev"),
    }


def read_result(u):
    """读结果页：总分、等级、点评、六项得分。"""
    def txt(i):
        n = u.by_id(i)
        return n.text if n else None

    items = []
    # 注意 ⏱️ 带变体选择符 U+FE0F，正则要允许，否则会漏掉「时间效率」
    head = re.compile(r"^[🔪🔥🧂📋⏱💡]\ufe0f?\s")
    nodes = u.nodes
    for idx, n in enumerate(nodes):
        if n.text and head.match(n.text) and n.center:
            for m in nodes[idx: idx + 6]:
                if m.text and re.fullmatch(r"\d+\s*/\s*\d+", m.text):
                    items.append((n.text, m.text))
                    break
    return {"total": txt("tv_total_score"), "level": txt("tv_score_level"),
            "feedback": txt("tv_feedback"), "items": items}


def profile_snapshot(u):
    """读个人信息页：昵称、忌口、三组口味的选项与当前选中项。"""
    def txt(i):
        n = u.by_id(i)
        return n.text if n else None
    groups = {}
    for key in ("rg_spice", "rg_sweet", "rg_salt"):
        g = u.by_id(key)
        if not g or not g.bounds:
            continue
        opts, chosen = [], None
        for r in u.nodes:
            if not r.cls.endswith("RadioButton") or not r.bounds:
                continue
            if g.bounds[1] <= r.bounds[1] <= g.bounds[3]:
                opts.append(r.text)
                if r.checked:
                    chosen = r.text
        groups[key] = {"options": opts, "checked": chosen}
    return {"nickname": txt("et_nickname"), "dislike": txt("et_dislike"),
            "levels": groups}


def visible_dish_list(u):
    """菜谱列表区里可见的菜名。

    列表卡片的菜名节点横向中心在 x>400；左侧分类栏在 x≈124 且带换行。
    据此把两者区分开，避免把分类标签当成菜名。
    """
    skip = {"全部", "川菜", "湘菜", "粤菜", "家常菜", "日料", "西餐",
            "韩餐", "东南亚/闽菜", "选择菜谱", "做", "去"}
    out = []
    for n in u.nodes:
        t = n.text
        if not t or not n.cls.endswith("TextView") or not n.center:
            continue
        if "\n" in t or "★" in t or t.startswith("⏱") or "|" in t:
            continue
        if t in skip or "选择" in t or "共" in t or "详情" in t or ">" in t:
            continue
        if n.center[1] < 560 or n.center[0] < 400:
            continue
        out.append(t)
    return out


def current_dialog():
    """返回当前对话框的 (标题, 正文, 按钮列表)，没有则 None。"""
    u = D.ui()
    title, msg = u.by_id("alertTitle"), u.by_id("message")
    if not title and not msg:
        return None
    btns = [n.text for n in u.nodes if n.cls.endswith("Button") and n.text]
    return (title.text if title else None, msg.text if msg else None, btns)


def close_dialog(prefer=("知道了", "取消", "继续烹饪")):
    """关掉阻断弹窗，返回 (标题, 正文)。同一张快照里找按钮，只抓一次界面。"""
    d = current_dialog()
    if not d:
        return None
    u = D.ui()
    for n in u.nodes:
        if n.text in prefer and n.center:
            D.tap(*n.center)
            # 显式等待：弹窗消失
            try:
                D.wait_ui(lambda x: x.by_id("alertTitle") is None, timeout=8,
                          desc="弹窗关闭")
            except Exception:
                pass
            break
    return d[0], d[1]


# ================================================================ 导航
def go_home():
    """回到首页，作为用例的干净起点。

    优先走"便宜路径"：已经在首页就直接返回；否则**只试一次返回键**并等焦点回首页
    （约 2.5s 上限）。试一次就够——从列表/详情/设置页返回一次必然到首页；而从烹饪页
    返回会弹确认框、从结果页返回会退出应用，这两种情况再按多少次也没用，直接冷启动
    更快、更稳。冷启动一次好几秒，能省则省。

    注意：HomeActivity 未导出（不是 exported），冷启动只能用启动页拉起。
    """
    # 息屏/锁屏时界面树是空的，会误判成"首页没有卡片"，所以先确保屏幕亮着
    D.ensure_awake()
    if HOME_ACT in D.current_focus():
        u = D.ui()
        if u.by_id("card_start_cooking") is not None:
            return u
    D.back()
    try:
        D.wait_focus(HOME_ACT, timeout=2.5)
        u = D.ui()
        if u.by_id("card_start_cooking") is not None:
            return u
    except Exception:
        pass
    D.force_stop(PKG)
    D.shell(f"am start -n {PKG}/.activities.SplashActivity")
    D.wait_focus(HOME_ACT, timeout=20, desc="冷启动进入首页")
    u = D.ui()
    # 兜底自愈：界面树整个是空的，说明又息屏/锁屏了，唤醒后再看一次
    if not u.nodes:
        D.ensure_awake()
        u = D.ui()
    return u


def open_recipe_list():
    """首页 -> 菜谱选择。不在首页时先回首页。"""
    if HOME_ACT not in D.current_focus():
        go_home()
    u = D.ui()
    card = u.by_id("card_start_cooking")
    if card is None:
        go_home()
        card = D.ui().by_id("card_start_cooking")
    D.tap(*card.center)
    D.wait_focus(LIST_ACT, timeout=15, desc="进入菜谱列表")
    return D.ui()


def open_dish_by_name(name, max_scroll=30):
    """在菜谱列表里滚动查找并打开指定菜名。

    中文无法通过 adb input text 输入，所以不走搜索框，直接滚动定位。
    返回 (是否找到, 滚动次数, 见过的菜名列表)。

    性能要点：每次循环只抓一次界面，用"上一张快照的内容签名"判断是否到底。

    滚动步长（实测数据，见 tools/scroll_probe.py）：input swipe 的实际滚动量
    约为手指位移的 1.4 倍（惯性）。可视窗口约 1700px，所以手指位移必须小于
    1700/1.4≈1214px，否则一次滚动跨过整个窗口、会直接跳过条目。取 900px
    手指位移 → 实际滚约 1250px → 相邻两帧仍重叠约 450px，既安全又少抓界面。
    """
    seen, prev_sig = [], None
    for i in range(max_scroll):
        u = D.ui()
        node = _find_option_node(u, name)
        if node is not None:
            # 菜名在上方，往上挪一点确保落进卡片热区
            D.tap(540, max(node.center[1], 600))
            return True, i, seen
        for t in visible_dish_list(u):
            if t not in seen:
                seen.append(t)
        if prev_sig == _visible_signature(u):
            break                       # 滑了但内容没变 → 到底了
        prev_sig = _visible_signature(u)
        D.swipe(540, 1800, 540, 900, 400)
    return False, max_scroll, seen


def choose_mode(mode_label):
    """菜谱卡片弹出的模式选择框。

    弹窗里的文字自身不可点，但父容器可点，点文字中心即可命中。
    """
    u = D.ui()
    for n in u.nodes:
        if n.text and mode_label in n.text and n.center:
            D.tap(*n.center)
            target = DETAIL_ACT if "详解" in mode_label else COOK_ACT
            try:
                D.wait_focus(target, timeout=15, desc=f"进入 {target}")
            except Exception:
                pass
            return True
    return False


def open_dish(dish):
    """首页 -> 列表 -> 打开菜谱的模式选择框。返回 (是否成功, 说明)。"""
    go_home()
    open_recipe_list()
    ok, sc, _ = open_dish_by_name(dish)
    if not ok:
        return False, f"列表里找不到「{dish}」（滚动 {sc} 次到底）"
    return True, f"滚动 {sc} 次找到"


# ================================================================ 烹饪
def select_options_by_names(names, max_scroll=12):
    """按菜谱数据给出的**顺序**点选选项名，返回没点到的名字列表。

    为什么能这么快：选项在界面上的排列顺序与数据里一致，且点击单选不会引起
    重排（已实测：连点三个同组选项，元素位置不变）。所以在同一张快照上可以
    连续命中多个目标，不必每点一次就重抓一次界面。
    只在"当前快照里已经没有可命中的目标、但还有剩"时才向下滚动一屏并重抓。
    """
    remaining = [n for n in names if n]
    if not remaining:
        return []
    u = D.ui()
    for _ in range(max_scroll):
        for nm in list(remaining):
            node = _find_option_node(u, nm)
            if node is not None:
                D.tap(540, node.center[1])
                remaining.remove(nm)
        if not remaining:
            return []
        before = _visible_signature(u)
        D.swipe(540, 1780, 540, 1250, 350)
        u = D.ui()
        if _visible_signature(u) == before:
            break                        # 滚到底了还是没找到
    return remaining


def step1_option_names(recipe):
    """第 1 步要选的选项名（每个食材每个选项组取第一项），以及没有可选项的食材。"""
    names, skipped = [], []
    for ing in (recipe.get("ingredients") or {}).values():
        opts = ing.get("options") or {}
        if not opts:
            skipped.append(ing.get("name"))
            continue
        for ov in opts.values():
            olist = (ov or {}).get("options") or []
            if olist:
                names.append(olist[0]["name"])
            else:
                skipped.append(ing.get("name"))
    return names, skipped


def flow_first_option(recipe, step_name):
    """按步骤名从数据里取该流程步骤的第一项选项名。"""
    for k, v in (recipe.get("cooking_flow") or {}).items():
        if v.get("name") == step_name:
            olist = v.get("options") or []
            return (olist[0]["name"] if olist else None), k, len(olist)
    return None, None, 0


def expected_flow(recipe):
    return [v.get("name") for v in (recipe.get("cooking_flow") or {}).values()]


def advance_step(progress_before, u=None, timeout=8.0):
    """点「下一步」，显式等待进度文字变化，返回 (新进度, 新快照)。

    返回快照是为了让调用方不用再抓一次（一次抓取约 2.4s）——等待过程本身
    就已经拿到了"推进后"的那一帧。
    """
    u = u or D.ui()
    btn = u.by_id("btn_next")
    if btn is None:
        return None, u
    D.tap(*btn.center)
    try:
        u2 = D.wait_id_text_change("tv_progress", progress_before,
                                   timeout=timeout,
                                   desc=f"步骤从 {progress_before} 推进")
    except Exception:
        # 没推进：可能是校验拦住了（会弹提示），关掉弹窗再看一眼
        close_dialog()
        u2 = D.ui()
    n = u2.by_id("tv_progress")
    return (n.text if n else None), u2


def finish_to_result(dish, recipe):
    """走完一道菜的助手模式（选项取数据里的第一项），返回过程记录。

    性能要点：每一步只抓 2 次界面——一次读步骤内容，一次是"等待推进"顺带拿到的
    新帧。不要把同一帧重复抓（一次抓取 2.4s，很容易把整轮拖长）。
    """
    log = {"steps": [], "dialogs": [], "result": None, "skipped_ingredients": [],
           "missed_options": []}
    ok, why = open_dish(dish)
    if not ok:
        log["error"] = why
        return log
    if not choose_mode("助手模式"):
        log["error"] = "点击菜谱后没有弹出烹饪模式选择框"
        return log
    d = close_dialog()
    if d:
        log["dialogs"].append(d)

    u = D.ui()
    for i in range(10):
        s = cooking_snapshot(u)
        if not s.get("progress"):
            break
        title = (s["step_title"] or "").replace("🤖", "").strip()
        title = title.split("：")[-1]
        rec = {"progress": s["progress"], "title": title,
               "timer": s["timer"], "desc": s["desc"]}
        if i == 0:
            want, skipped = step1_option_names(recipe)
            rec["should_pick"] = want
            rec["failed_pick"] = select_options_by_names(want)
            log["skipped_ingredients"] = skipped
        else:
            nm, key, cnt = flow_first_option(recipe, title)
            rec["data_key"] = key
            rec["data_option_count"] = cnt
            rec["picked"] = nm
            rec["failed_pick"] = select_options_by_names([nm])
        log["steps"].append(rec)
        if rec["failed_pick"]:
            log["missed_options"].append((title, rec["failed_pick"]))

        new_prog, u = advance_step(s["progress"], u)
        if new_prog == s["progress"]:
            # 被校验拦住：补选一次再推进
            again = (step1_option_names(recipe)[0] if i == 0
                     else [flow_first_option(recipe, title)[0]])
            select_options_by_names(again)
            new_prog, u = advance_step(s["progress"])
        if u.by_id("tv_total_score"):
            log["result"] = read_result(u)
            break
    return log


# ================================================================ 列表页操作
def click_category(label, timeout=10.0):
    """点左侧分类标签，并显式等待"当前分类"文字变成该标签。"""
    u = D.ui()
    for n in u.nodes:
        if n.text and label in n.text and n.clickable and n.center:
            D.tap(*n.center)
            try:
                D.wait_id_text("tv_current_category", label, timeout=timeout,
                               desc=f"分类切到 {label}")
            except Exception:
                D.ui()      # 兜底：至少保证下一次读到新界面
            return True
    return False


def search(kw):
    """在搜索框输入关键词（非 ASCII 本机输不了，见项目记忆）。"""
    u = D.ui()
    box = u.by_id("et_search")
    if not box:
        return False
    D.tap(*box.center)
    wait_keyboard_shown()
    D.shell("input keyevent 123")
    for _ in range(20):
        D.shell("input keyevent 67")
    D.invalidate()
    if kw:
        D.shell(f'input text "{kw}"', check=False)
        D.invalidate()
    return True


def clear_search():
    u = D.ui()
    box = u.by_id("et_search")
    if not box or not box.center:
        return False
    D.tap(*box.center)
    wait_keyboard_shown()
    D.shell("input keyevent 123")
    for _ in range(40):
        D.shell("input keyevent 67")
    D.invalidate()
    return True


def hide_keyboard(timeout=6.0):
    D.shell("input keyevent 111")
    D.invalidate()
    return wait_keyboard_hidden(timeout)


def _ime_state():
    out = D.shell("dumpsys input_method", check=False)
    return "mInputShown=true" in out


def wait_keyboard_shown(timeout=5.0):
    """显式等待软键盘弹出（用 dumpsys input_method，约 0.2s/次，很便宜）。"""
    try:
        return D.until(_ime_state, timeout=timeout, interval=0.15,
                       desc="软键盘弹出")
    except Exception:
        return False


def wait_keyboard_hidden(timeout=5.0):
    try:
        return D.until(lambda: not _ime_state(), timeout=timeout, interval=0.15,
                       desc="软键盘收起")
    except Exception:
        return False


# ================================================================ 通用等待辅助
def wait_radio_checked(name, timeout=8.0):
    """等某个选项名对应的单选框进入选中态（tap 之后的正确同步方式）。"""
    def pred(u):
        for g in option_groups(u):
            for r in g:
                if r.checked and option_name(u, r) == name:
                    return True
        return False
    return D.wait_ui(pred, timeout, f"「{name}」被选中")


def select_radio(name, timeout=8.0):
    """按选项名点选单选框，并显式等待它真的变成选中态。"""
    u = D.ui()
    node = _find_option_node(u, name)
    if node is None:
        return False
    D.tap(540, node.center[1])
    try:
        wait_radio_checked(name, timeout)
    except Exception:
        return False
    return True


def wait_user_config_change(before, timeout=8.0):
    """等 user_config.json 和 before 不同；超时返回最新内容（说明没变）。

    读文件很便宜（约 0.1s），所以这里可以密集轮询，比睡固定时长快得多也可靠。
    """
    try:
        return D.wait_file(read_user_config, lambda c: c != before,
                           timeout=timeout, interval=0.25,
                           desc="user_config.json 落盘")
    except Exception:
        return read_user_config()


def wait_dialog(timeout=8.0):
    """等出现阻断弹窗，返回 (标题, 正文, 按钮)；超时返回 None。"""
    try:
        D.wait_ui(lambda u: u.by_id("alertTitle") is not None,
                  timeout=timeout, desc="弹窗出现")
    except Exception:
        return None
    return current_dialog()
