# -*- coding: utf-8 -*-
"""极简测试框架：用例注册、断言、失败截图、报告生成。

设计目标：
- 零第三方依赖，只用 adb
- 失败时自动留证据（截图 + 界面 dump），省去人工复现
- 报告输出 Markdown + HTML 两份
"""
import os
import re
import time
import traceback

from . import device as D

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(PROJ, "reports")
EVIDENCE = os.path.join(PROJ, "evidence")

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
SEV_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

PKG = "com.example.kitchenassistant"
HOME = ".activities.HomeActivity"


class CaseResult:
    def __init__(self, cid, title, group, severity):
        self.cid = cid
        self.title = title
        self.group = group
        self.severity = severity
        self.status = None
        self.detail = ""
        self.notes = []
        self.evidence = []
        self.started = None
        self.elapsed = 0.0

    @property
    def ok(self):
        return self.status in (PASS, SKIP)


class CaseFail(AssertionError):
    """断言失败，带上给报告看的说明。"""


def check(cond, msg):
    if not cond:
        raise CaseFail(msg)


def check_eq(actual, expected, what):
    if actual != expected:
        raise CaseFail(f"{what}: 期望 {expected!r}，实际 {actual!r}")


def check_in(needle, haystack, what):
    if needle not in haystack:
        raise CaseFail(f"{what}: {needle!r} 未出现在 {haystack!r}")


CASES = []          # [(cid, title, group, severity, fn)]


def case(cid, title, group, severity="P2"):
    """注册一个用例。fn 签名 (runner, result)。"""
    def deco(fn):
        CASES.append((cid, title, group, severity, fn))
        return fn
    return deco


class Runner:
    def __init__(self):
        self.results = []
        self.only = None

    # ---------------------------------------------------------- 环境
    def preflight(self):
        devs = D.devices()
        if not devs:
            raise RuntimeError("没有检测到已连接的 Android 设备，请检查 adb devices")
        D.wait_for_device()
        self.width, self.height = D.screen_size()
        return devs[0]

    # ---------------------------------------------------------- 执行
    def run(self, only=None):
        """only: 字符串或字符串列表，命中任一即执行（按编号或标题子串匹配）。"""
        if isinstance(only, str):
            only = [only]
        self.only = only
        for cid, title, group, severity, fn in CASES:
            if only and not any(k in cid or k in title for k in only):
                continue
            r = CaseResult(cid, title, group, severity)
            r.started = time.time()
            print(f"  ▶ {cid} {title} ... ", end="", flush=True)
            try:
                fn(self, r)
                if r.status is None:
                    r.status = PASS
            except CaseFail as e:
                r.status = FAIL
                r.detail = str(e)
            except Exception as e:
                r.status = FAIL
                r.detail = f"用例异常: {e.__class__.__name__}: {e}"
                r.notes.append(traceback.format_exc(limit=3))
            r.elapsed = time.time() - r.started
            if r.status == FAIL:
                tag = re.sub(r"[^\w]", "_", cid)
                try:
                    r.evidence.append(os.path.relpath(D.screenshot(f"fail_{tag}"), PROJ))
                    ui = D.dump_ui()
                    p = os.path.join(EVIDENCE, f"fail_{tag}_ui.txt")
                    with open(p, "w", encoding="utf-8") as fh:
                        fh.write(f"# {cid} {title}\n{r.detail}\n\n{ui.dump()}")
                    r.evidence.append(os.path.relpath(p, PROJ))
                except Exception:
                    pass
            print(r.status + ("" if r.status != FAIL else f"  <- {r.detail}"))
            self.results.append(r)
        return self.results

    # ---------------------------------------------------------- 报告
    def summary(self):
        s = {PASS: 0, FAIL: 0, WARN: 0, SKIP: 0}
        for r in self.results:
            s[r.status] = s.get(r.status, 0) + 1
        return s


# ------------------------------------------------------------------ 报告
def _by_group(results):
    groups = {}
    for r in results:
        groups.setdefault(r.group, []).append(r)
    return groups


def write_markdown(results, meta, path):
    s = {PASS: 0, FAIL: 0, WARN: 0, SKIP: 0}
    for r in results:
        s[r.status] = s.get(r.status, 0) + 1
    total = len(results)
    rate = (s[PASS] / total * 100) if total else 0

    L = []
    L.append(f"# {meta.get('title', '测试报告')}\n")
    L.append(f"- 被测应用：**{meta['app']}** (`{meta['pkg']}`)")
    L.append(f"- 版本：{meta['version']}")
    L.append(f"- 设备：{meta['device']}")
    L.append(f"- 执行时间：{meta['started']} ~ {meta['finished']}")
    L.append(f"- 总耗时：{meta['elapsed']:.0f} 秒")
    L.append("")
    L.append("## 结果概览\n")
    L.append("| 指标 | 数量 |")
    L.append("|---|---|")
    L.append(f"| 用例总数 | {total} |")
    L.append(f"| 通过 | {s[PASS]} |")
    L.append(f"| 失败 | {s[FAIL]} |")
    L.append(f"| 通过率 | {rate:.1f}% |")
    L.append("")

    fails = [r for r in results if r.status == FAIL]
    if fails:
        L.append("## 缺陷清单（按严重程度排序）\n")
        fails_sorted = sorted(fails, key=lambda r: SEV_ORDER.get(r.severity, 9))
        L.append("| 编号 | 严重度 | 所属模块 | 问题描述 |")
        L.append("|---|---|---|---|")
        for r in fails_sorted:
            L.append(f"| {r.cid} | {r.severity} | {r.group} | {r.detail} |")
        L.append("")

    for g, rs in _by_group(results).items():
        L.append(f"## {g}\n")
        L.append("| 用例 | 严重度 | 结果 | 说明 | 耗时 |")
        L.append("|---|---|---|---|---|")
        for r in rs:
            d = r.detail.replace("\n", " ")[:160] if r.detail else ""
            L.append(f"| {r.cid} {r.title} | {r.severity} | {r.status} | {d} | {r.elapsed:.1f}s |")
        L.append("")
        for r in rs:
            if r.evidence:
                L.append(f"- {r.cid} 证据：{', '.join(r.evidence)}")
        L.append("")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L))
    return path


def write_html(results, meta, path):
    s = {PASS: 0, FAIL: 0, WARN: 0, SKIP: 0}
    for r in results:
        s[r.status] = s.get(r.status, 0) + 1
    total = len(results)
    rate = (s[PASS] / total * 100) if total else 0

    def esc(t):
        return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    color = {PASS: "#1a7f37", FAIL: "#cf222e", WARN: "#9a6700", SKIP: "#57606a"}
    fails = sorted([r for r in results if r.status == FAIL],
                   key=lambda r: SEV_ORDER.get(r.severity, 9))

    rows = []
    for g, rs in _by_group(results).items():
        rows.append(f'<tr class="grp"><td colspan="5">{esc(g)}</td></tr>')
        for r in rs:
            ev = "".join(f'<div class="ev">{esc(e)}</div>' for e in r.evidence)
            rows.append(
                f'<tr><td class="cid">{esc(r.cid)}</td>'
                f'<td class="sev {r.severity}">{r.severity}</td>'
                f'<td>{esc(r.title)}</td>'
                f'<td class="st" style="color:{color[r.status]}">{r.status}</td>'
                f'<td>{esc(r.detail)}{ev}</td></tr>')

    defect = ""
    if fails:
        defect = "<h2>缺陷清单</h2><table><tr><th>编号</th><th>严重度</th>" \
                 "<th>模块</th><th>问题</th></tr>"
        for r in fails:
            defect += (f'<tr><td class="cid">{esc(r.cid)}</td>'
                       f'<td class="sev {r.severity}">{r.severity}</td>'
                       f'<td>{esc(r.group)}</td><td>{esc(r.detail)}</td></tr>')
        defect += "</table>"

    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{esc(meta.get('title','测试报告'))}</title>
<style>
 body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;
   margin:0;padding:32px;background:#f6f8fa;color:#1f2328;line-height:1.6}}
 h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:28px 0 10px}}
 .meta{{color:#57606a;font-size:13px;margin-bottom:18px}}
 .cards{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px}}
 .card{{background:#fff;border:1px solid #d0d7de;border-radius:10px;
   padding:12px 18px;min-width:96px}}
 .card b{{display:block;font-size:22px}} .card span{{font-size:12px;color:#57606a}}
 table{{border-collapse:collapse;width:100%;background:#fff;font-size:13px;
   border:1px solid #d0d7de;border-radius:8px;overflow:hidden}}
 th,td{{border-bottom:1px solid #eaeef2;padding:8px 10px;text-align:left;
   vertical-align:top}}
 th{{background:#f6f8fa;font-weight:600}} .grp td{{background:#eef2f6;font-weight:600}}
 .cid{{font-family:ui-monospace,Consolas,monospace;white-space:nowrap}}
 .st{{font-weight:600}} .ev{{font-family:ui-monospace,Consolas,monospace;
   font-size:11px;color:#57606a}}
 .sev{{font-weight:600;white-space:nowrap}}
 .P0{{color:#cf222e}} .P1{{color:#bc4c00}} .P2{{color:#9a6700}} .P3{{color:#57606a}}
</style></head><body>
<h1>{esc(meta.get('title','测试报告'))}</h1>
<div class="meta">应用 {esc(meta['app'])} ({esc(meta['pkg'])}) · 版本 {esc(meta['version'])}
 · 设备 {esc(meta['device'])} · {esc(meta['started'])} ~ {esc(meta['finished'])}
 · 耗时 {meta['elapsed']:.0f}s</div>
<div class="cards">
 <div class="card"><b>{total}</b><span>用例总数</span></div>
 <div class="card"><b style="color:{color[PASS]}">{s[PASS]}</b><span>通过</span></div>
 <div class="card"><b style="color:{color[FAIL]}">{s[FAIL]}</b><span>失败</span></div>
 <div class="card"><b>{rate:.1f}%</b><span>通过率</span></div>
</div>
{defect}
<h2>全部用例</h2>
<table><tr><th>编号</th><th>严重度</th><th>用例</th><th>结果</th><th>说明</th></tr>
{''.join(rows)}
</table></body></html>"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return path
