# -*- coding: utf-8 -*-
"""ADB 设备操作封装：无第三方依赖，只用 adb 命令行。"""
import os
import re
import time
import subprocess
import xml.etree.ElementTree as ET

from .waits import until, WaitTimeout, FAST_INTERVAL, UI_INTERVAL  # noqa: F401

ADB = os.environ.get("ADB_BIN", "adb")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVIDENCE = os.path.join(PROJ, "evidence")

# 无线调试掉线时用于自动重连的地址（可在环境变量里覆盖）
RECONNECT_TARGETS = os.environ.get("MIMO_ADB_RECONNECT",
                                   "192.168.1.102:5555").split(",")


class AdbError(RuntimeError):
    pass


def _try_reconnect():
    """设备掉线时尝试重连。返回是否重连成功。

    重连是异步的（connect 返回后设备还要几秒才可用），所以这里用显式等待
    轮询 devices() 直到真能看到设备，而不是睡固定时长。
    """
    subprocess.run([ADB, "connect"] + [t.strip() for t in RECONNECT_TARGETS if t.strip()],
                   capture_output=True, timeout=20)
    try:
        return until(lambda: bool(devices()), timeout=15, interval=0.5,
                     desc="adb 设备重连")
    except Exception:
        return False


def run(args, timeout=30, binary=False, check=True, _retry=True):
    cmd = [ADB] + args
    try:
        p = subprocess.run(
            cmd, capture_output=True, timeout=timeout,
            **({} if binary else {"encoding": "utf-8", "errors": "replace"}),
        )
    except subprocess.TimeoutExpired:
        if _retry:
            _try_reconnect()
            return run(args, timeout, binary, check, _retry=False)
        raise
    if p.returncode != 0 and check:
        err = p.stderr
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        # 设备掉线时自动重连并重试一次
        if _retry and any(k in err for k in ("no devices", "device offline",
                                             "device not found", "closed")):
            if _try_reconnect():
                return run(args, timeout, binary, check, _retry=False)
        raise AdbError(f"{' '.join(cmd)} 失败: {err.strip()[:500]}")
    return p.stdout


def shell(cmd, timeout=30, check=True):
    return run(["shell", cmd], timeout=timeout, check=check)


# ---------------------------------------------------------------- 设备
def devices():
    out = run(["devices"])
    return [l.split()[0] for l in out.splitlines()[1:] if l.strip() and "device" in l]


def wait_for_device(timeout=30):
    run(["wait-for-device"], timeout=timeout)


def screen_size():
    out = shell("wm size")
    m = re.search(r"Override size:\s*(\d+)x(\d+)", out) or re.search(r"Physical size:\s*(\d+)x(\d+)", out)
    if not m:
        raise AdbError("无法获取屏幕尺寸: " + out)
    return int(m.group(1)), int(m.group(2))


# ---------------------------------------------------------------- 应用
def current_focus():
    """返回当前聚焦的 Activity 全名，如 com.x/.A。"""
    out = shell("dumpsys window")
    m = re.search(r"mCurrentFocus=Window\{[^}]*?\s+([\w.]+/[\w.$]+)\}", out)
    if m:
        return m.group(1)
    m = re.search(r"mFocusedApp=ActivityRecord\{[^}]*?\s+([\w.]+/[\w.$]+)", out)
    return m.group(1) if m else ""


def start_activity(pkg, activity, **_):
    """拉起 Activity。不做等待——调用方要用 wait_focus() 等目标界面出现。"""
    shell(f"am start -n {pkg}/{activity}")
    invalidate("start activity")


def force_stop(pkg):
    shell(f"am force-stop {pkg}")
    invalidate("force stop")


def clear_app(pkg):
    shell(f"pm clear {pkg}")
    invalidate("clear app")


# ---------------------------------------------------------------- 屏幕状态
# 息屏/锁屏时 uiautomator 抓到的界面树是**空的**，所有界面用例都会误判成
# "元素不存在"。所以跑之前必须确保屏幕点亮且已解锁。
def is_awake():
    out = shell("dumpsys power", check=False)
    return "mWakefulness=Awake" in out


def is_locked():
    """锁屏/下拉通知栏状态。"""
    focus = current_focus()
    return "NotificationShade" in focus or "Keyguard" in focus


def ensure_awake(timeout=15.0):
    """点亮屏幕并解锁。返回是否成功（成功=屏幕亮且不在锁屏）。"""
    if is_awake() and not is_locked():
        return True
    shell("input keyevent 224")          # KEYCODE_WAKEUP
    try:
        until(is_awake, timeout=timeout * 0.4, interval=0.3, desc="屏幕点亮")
    except WaitTimeout:
        pass
    shell("wm dismiss-keyguard", check=False)
    invalidate("wake up")
    try:
        until(lambda: is_awake() and not is_locked(), timeout=timeout,
              interval=0.3, desc="屏幕点亮且解锁")
        return True
    except WaitTimeout:
        return False


def is_running(pkg):
    out = shell("pidof " + pkg, check=False)
    return bool(out.strip())


def logcat_dump(tag_filter=None, lines=200):
    cmd = f"logcat -d -t {lines}"
    if tag_filter:
        cmd += f" -s {tag_filter}"
    return shell(cmd, check=False)


def logcat_clear():
    shell("logcat -c", check=False)


# ---------------------------------------------------------------- 输入
# 注意：这些函数**不做任何等待**。点击是异步的，调用方要用 waits.until()
# 轮询自己关心的状态，而不是睡固定时长（项目规范：禁止硬等待）。
def tap(x, y, **_):
    shell(f"input tap {int(x)} {int(y)}")
    invalidate()


def long_press(x, y, ms=1200, **_):
    shell(f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(ms)}")
    invalidate()


def swipe(x1, y1, x2, y2, ms=300, **_):
    shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(ms)}")
    invalidate()


def scroll_down(times=1, **_):
    w, h = screen_size()
    for _ in range(times):
        swipe(w // 2, int(h * 0.72), w // 2, int(h * 0.32), 300)


def scroll_up(times=1, **_):
    w, h = screen_size()
    for _ in range(times):
        swipe(w // 2, int(h * 0.32), w // 2, int(h * 0.72), 300)


def input_text(text, **_):
    """输入文本。注意本机对非 ASCII（中文）会直接抛异常，见项目记忆。"""
    safe = text.replace(" ", "%s")
    shell(f'input text "{safe}"')
    invalidate()


def keyevent(code, **_):
    shell(f"input keyevent {code}")
    invalidate()


def back(**_):
    keyevent(4)


def screenshot(name):
    os.makedirs(EVIDENCE, exist_ok=True)
    remote = f"/sdcard/_ev_{name}.png"
    shell(f"screencap -p {remote}")
    local = os.path.join(EVIDENCE, f"{name}.png")
    run(["pull", remote, local], check=False)
    shell(f"rm -f {remote}", check=False)
    return local


# ---------------------------------------------------------------- 界面
class Node:
    __slots__ = ("text", "desc", "rid", "cls", "pkg", "bounds", "attrs", "raw")

    def __init__(self, attrs):
        self.attrs = attrs
        self.text = (attrs.get("text") or "").strip()
        self.desc = (attrs.get("content-desc") or "").strip()
        self.rid = (attrs.get("resource-id") or "").strip()
        self.cls = (attrs.get("class") or "").strip()
        self.pkg = (attrs.get("package") or "").strip()
        self.bounds = self._parse(attrs.get("bounds"))
        self.raw = attrs

    @staticmethod
    def _parse(b):
        m = re.findall(r"-?\d+", b or "")
        if len(m) != 4:
            return None
        return tuple(map(int, m))

    @property
    def short_id(self):
        return self.rid.rsplit("/", 1)[-1] if "/" in self.rid else self.rid

    @property
    def center(self):
        if not self.bounds:
            return None
        x1, y1, x2, y2 = self.bounds
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @property
    def clickable(self):
        return self.raw.get("clickable") == "true"

    @property
    def enabled(self):
        return self.raw.get("enabled") != "false"

    @property
    def displayed(self):
        """bounds 非零且宽高 > 0 才算真正可见。"""
        if not self.bounds:
            return False
        x1, y1, x2, y2 = self.bounds
        return x2 > x1 and y2 > y1

    @property
    def checked(self):
        return self.raw.get("checked") == "true"

    def __repr__(self):
        return f"<Node {self.cls.rsplit('.',1)[-1]} text={self.text!r} id={self.short_id} @{self.center}>"


class Ui:
    """一次界面快照，支持按 id / text / desc 查找元素。"""

    def __init__(self, xml_text, pkg=None):
        self.nodes = []
        root = ET.fromstring(xml_text)
        self._walk(root)
        self.pkg = pkg

    def _walk(self, el):
        if el.tag == "node":
            self.nodes.append(Node(el.attrib))
        for ch in el:
            self._walk(ch)

    # -- 查询
    def by_id(self, short_id, index=0):
        hits = [n for n in self.nodes if n.short_id == short_id]
        return hits[index] if len(hits) > index else None

    def all_by_id(self, short_id):
        return [n for n in self.nodes if n.short_id == short_id]

    def by_text(self, text, exact=False, index=0, contains_any=False):
        hits = []
        for n in self.nodes:
            if not n.text:
                continue
            if exact:
                ok = n.text == text
            elif contains_any:
                ok = text in n.text
            else:
                ok = text == n.text or text in n.text
            if ok:
                hits.append(n)
        return hits[index] if len(hits) > index else None

    def all_by_text(self, text, exact=False):
        return [n for n in self.nodes
                if n.text and (n.text == text if exact else text in n.text)]

    def by_desc(self, desc, index=0):
        hits = [n for n in self.nodes if n.desc and desc in n.desc]
        return hits[index] if len(hits) > index else None

    def by_class(self, cls_short):
        return [n for n in self.nodes if n.cls.endswith(cls_short)]

    def clickable_nodes(self):
        return [n for n in self.nodes if n.clickable and n.displayed]

    def texts(self):
        return [n.text for n in self.nodes if n.text]

    def all_text(self):
        return "\n".join(self.texts())

    def edits(self):
        return [n for n in self.nodes
                if n.cls.endswith("EditText") or "EditText" in n.cls
                or n.raw.get("password") == "true"]

    def checkboxes(self):
        return [n for n in self.nodes if n.raw.get("checkable") == "true"
                or n.cls.endswith("CheckBox") or n.cls.endswith("Switch")]

    def to_listing(self):
        out = []
        for n in self.nodes:
            if n.text or n.desc or n.rid or n.clickable:
                f = []
                if n.clickable:
                    f.append("click")
                if n.raw.get("scrollable") == "true":
                    f.append("scroll")
                if n.raw.get("checkable") == "true":
                    f.append("checkable")
                if n.checked:
                    f.append("CHECKED")
                if not n.enabled:
                    f.append("DISABLED")
                if n.raw.get("selected") == "true":
                    f.append("sel")
                line = f"<{n.cls.rsplit('.',1)[-1]}>"
                if n.text:
                    line += f" text={n.text!r}"
                if n.desc:
                    line += f" desc={n.desc!r}"
                if n.rid:
                    line += f" id={n.short_id}"
                if n.center:
                    line += f" @{n.center[0]},{n.center[1]}"
                if f:
                    line += " [" + ",".join(f) + "]"
                out.append(line)
        return "\n".join(out)

    def dump(self, path=None):
        text = self.to_listing()
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        return text


# ---------------------------------------------------------------- 界面快照
_SNAPSHOT = {"ui": None, "at": 0.0, "reason": "init"}
DUMP_COST_HINT = 2.4          # 本机实测一次 dump 约 2.4s，用于日志提示


def invalidate(reason="input"):
    """任何输入动作后调用：告诉缓存"界面可能变了，下次必须重新抓"。"""
    _SNAPSHOT["ui"] = None
    _SNAPSHOT["reason"] = reason


def snapshot_age():
    if _SNAPSHOT["ui"] is None:
        return None
    return round(time.monotonic() - _SNAPSHOT["at"], 2)


def ui():
    """取当前界面快照。同一次"输入之间的间隔内"复用同一个快照。

    uiautomator dump 在本机约 2.4 秒/次，而一次用例里往往需要反复读同一个界面，
    所以做缓存：只要没有发生过输入（tap/swipe/back/input_text/keyevent），
    就复用上一次的结果。这既省时间，也避免"两次读到不同帧"导致的偶发失败。
    """
    if _SNAPSHOT["ui"] is not None:
        return _SNAPSHOT["ui"]
    xml_text = _dump_xml()
    parsed = Ui(xml_text)
    _SNAPSHOT["ui"] = parsed
    _SNAPSHOT["at"] = time.monotonic()
    return parsed


def _clean_xml(raw):
    """从原始输出里截出干净的 XML。

    `uiautomator dump /dev/tty` 会在 XML 后面再打一行 "UI hierchary dumped to: ..."，
    直接丢给 ET 会报 "junk after document element"，所以要按 </hierarchy> 截断。
    """
    if not raw or "<hierarchy" not in raw:
        return None
    start = raw.index("<?xml") if "<?xml" in raw else raw.index("<hierarchy")
    end = raw.rindex("</hierarchy>") + len("</hierarchy>")
    return raw[start:end]


def _dump_xml(retries=3):
    """抓一次界面 XML。

    优先用 exec-out /dev/tty：一次 adb 调用就能拿到 XML，比"dump 到文件再 cat"
    少一次往返（本机实测一次抓取约 2.4s，省下的往返很值）。失败则回退文件方式。
    """
    last = None
    for _ in range(retries):
        cleaned = _clean_xml(run(["exec-out", "uiautomator", "dump", "/dev/tty"],
                                 check=False))
        if cleaned:
            return cleaned
        last = "exec-out 方式未返回有效 XML"
        run(["shell", "uiautomator dump /sdcard/_ui.xml"], check=False)
        cleaned = _clean_xml(run(["shell", "cat /sdcard/_ui.xml"], check=False))
        if cleaned:
            return cleaned
        last = "文件方式也未返回有效 XML"
    raise AdbError(f"UI 抓取失败: {last}")


def dump_ui(pkg=None, retries=3):
    """强制重新抓取（忽略缓存）。需要"绝对最新的界面"时用这个。"""
    invalidate("explicit dump")
    return ui()


# ---------------------------------------------------------------- 显式等待
# 命名约定：wait_* 一律"轮询直到成立，成立即返回界面快照；超时抛 WaitTimeout"。
# 统一返回快照是为了让调用方能直接接着断言，而且拿到的是刚抓的那一张（有缓存，
# 不会再花一次 2.4s）。
def wait_focus(needle, timeout=12.0, desc=None):
    """等当前聚焦的 Activity 名称包含 needle。走 dumpsys，约 0.18s/次，很便宜。"""
    return until(lambda: needle in current_focus(), timeout, FAST_INTERVAL,
                 desc or f"界面切换到 {needle}")


def wait_ui(pred, timeout=12.0, desc="界面条件"):
    """等界面满足 pred(ui)，返回满足条件的那张快照。

    每次轮询都会重新抓界面（约 2.4s），所以要克制使用。
    """
    until(lambda: pred(dump_ui()), timeout, UI_INTERVAL, desc)
    return ui()


def wait_id(rid, timeout=12.0, desc=None):
    """等带某 resource-id 的元素出现，返回快照。"""
    return wait_ui(lambda u: u.by_id(rid) is not None, timeout,
                   desc or f"元素 {rid} 出现")


def wait_text(text, timeout=12.0, desc=None):
    return wait_ui(lambda u: u.by_text(text) is not None, timeout,
                   desc or f"文字「{text}」出现")


def wait_id_gone(rid, timeout=8.0, desc=None):
    return wait_ui(lambda u: u.by_id(rid) is None, timeout,
                   desc or f"元素 {rid} 消失")


def wait_id_text(rid, expected, timeout=12.0, desc=None):
    """等某元素的文字变成期望值（用于"分类切到川菜"这类判断）。"""
    def pred(u):
        n = u.by_id(rid)
        return n is not None and n.text == expected
    return wait_ui(pred, timeout, desc or f"{rid} 变为 {expected!r}")


def wait_id_text_change(rid, old_text, timeout=12.0, desc=None):
    """等某元素的文字不再是 old_text（用于"进度 1/4 → 2/4"这类判断）。"""
    def pred(u):
        n = u.by_id(rid)
        return n is not None and n.text != old_text
    return wait_ui(pred, timeout, desc or f"{rid} 从 {old_text!r} 变化")


def wait_file(loader, pred, timeout=12.0, interval=0.25, desc="配置文件更新"):
    """等读取到的文件内容满足 pred（读文件很便宜，可以密集轮询）。"""
    return until(lambda: pred(loader()), timeout, interval, desc)
