# -*- coding: utf-8 -*-
"""pytest 全局配置与 fixture。

对应项目规范：「pytest 加 allure 参数生成报告」。
这里做三件事：
  1. 会话开始时做一次设备预检，并生成 allure 的 environment.properties；
  2. 每个用例的界面/数据证据在失败时自动挂到 allure 上，同时落盘到 evidence/；
  3. 会话结束时把结果汇总成 Markdown + HTML 报告（给人看的那种）。
"""
import os
import sys
import time
import datetime

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from kitchen_test import device as D              # noqa: E402
from kitchen_test import framework as F           # noqa: E402
from kitchen_test import pages as P               # noqa: E402
import kitchen_test.cases_data                    # noqa: E402,F401  注册离线用例
import kitchen_test.cases_ui                      # noqa: E402,F401  注册界面用例

# 会话级结果表：cid -> CaseResult（用例体里写入，报告阶段读取）
RESULTS = {}
SESSION = {"started": None, "device": "未知", "version": "未知"}


def _app_version():
    out = D.shell("dumpsys package com.example.kitchenassistant")
    for line in out.splitlines():
        if "versionName" in line:
            return line.strip()
    return "未知"


def _device_name():
    out = D.run(["devices", "-l"])
    for line in out.splitlines():
        if "model:" in line:
            for p in line.split():
                if p.startswith("model:"):
                    return p.replace("model:", "")
    return "未知设备"


@pytest.fixture(scope="session", autouse=True)
def device_session():
    """整个会话只做一次设备预检；顺手把环境信息写进 allure。"""
    SESSION["started"] = time.time()
    devs = D.devices()
    if not devs:
        pytest.exit("没有检测到已连接的 Android 设备，请检查 `adb devices`", returncode=1)
    D.wait_for_device()

    # 息屏/锁屏时界面树是空的，会把所有界面用例误判成"元素不存在"，
    # 所以在最开始就点亮并解锁；唤醒不了就直接退出并说明原因，别让它静默误报。
    if not D.ensure_awake(timeout=15):
        pytest.exit("手机屏幕处于息屏/锁屏状态且无法自动唤醒。\n"
                    "请点亮并解锁手机（建议在开发者选项里打开「充电时屏幕不休眠」或手动保持常亮），"
                    "然后重新运行。", returncode=1)

    SESSION["device"] = _device_name()
    SESSION["version"] = _app_version()

    # 备份用户配置，测试结束后恢复（避免把被测环境改乱）
    try:
        SESSION["config_backup"] = P.backup_user_config()
    except Exception:
        SESSION["config_backup"] = None

    try:
        import allure
        ad = os.environ.get("ALLURE_RESULTS_DIR", os.path.join(ROOT, "allure-results"))
        os.makedirs(ad, exist_ok=True)
        with open(os.path.join(ad, "environment.properties"), "w",
                  encoding="utf-8") as fh:
            fh.write(f"App=厨房小能手\nPackage={P.PKG}\nAppVersion={SESSION['version']}\n"
                     f"Device={SESSION['device']}\n"
                     f"Python={sys.version.split()[0]}\n"
                     f"Adapter=adb (纯命令行, 零第三方依赖)\n")
    except Exception:
        pass

    yield SESSION

    if SESSION.get("config_backup") is not None:
        try:
            P.restore_user_config(SESSION["config_backup"])
            print("\n已恢复 user_config.json")
        except Exception as e:
            print("\n警告：恢复 user_config.json 失败:", e)


def attach_failure(cid, message):
    """把失败现场（截图 + 界面结构）挂到 allure，并落盘留证。"""
    paths = []
    try:
        img = D.screenshot(f"fail_{cid}")
        paths.append(img)
        try:
            import allure
            allure.attach.file(img, name=f"{cid} 失败截图",
                               attachment_type=allure.attachment_type.PNG)
        except Exception:
            pass
    except Exception:
        pass
    try:
        txt = D.dump_ui().dump()
        p = os.path.join(F.EVIDENCE, f"fail_{cid}_ui.txt")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(f"# {cid}\n{message}\n\n{txt}")
        paths.append(p)
        try:
            import allure
            allure.attach(txt, name=f"{cid} 界面结构",
                          attachment_type=allure.attachment_type.TEXT)
        except Exception:
            pass
    except Exception:
        pass
    return paths


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when != "call":
        return
    spec = getattr(item, "callspec", None)
    if not spec:
        return
    cid = spec.params.get("cid")
    res = RESULTS.get(cid)
    if res is None:
        return
    if rep.passed:
        if res.status not in ("WARN", "SKIP"):
            res.status = "PASS"
    elif rep.skipped:
        res.status = "SKIP"
        res.detail = res.detail or "用例主动跳过"
    else:
        res.status = "FAIL"
        res.detail = res.detail or (rep.longreprtext or "").strip()[:600]
        res.evidence = attach_failure(cid, res.detail)


def pytest_sessionfinish(session, exitstatus):
    """把结果汇总成 Markdown + HTML 报告（给人看的那份）。"""
    from kitchen_test.framework import PASS, FAIL, WARN, SKIP
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    rows = sorted(RESULTS.values(), key=lambda r: (r.group, order.get(r.severity, 9), r.cid))
    if not rows:
        return
    meta = {
        "title": "厨房小能手 App 自动化测试报告",
        "app": "厨房小能手",
        "pkg": P.PKG,
        "version": SESSION.get("version", "未知"),
        "device": SESSION.get("device", "未知"),
        "started": datetime.datetime.fromtimestamp(
            SESSION.get("started") or time.time()).strftime("%Y-%m-%d %H:%M:%S"),
        "finished": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed": time.time() - (SESSION.get("started") or time.time()),
    }
    os.makedirs(F.REPORT_DIR, exist_ok=True)
    md = F.write_markdown(rows, meta, os.path.join(F.REPORT_DIR, "测试执行记录.md"))
    html = F.write_html(rows, meta, os.path.join(F.REPORT_DIR, "测试执行记录.html"))
    stamp = datetime.datetime.fromtimestamp(
        SESSION.get("started") or time.time()).strftime("%Y%m%d_%H%M%S")
    arch = os.path.join(F.REPORT_DIR, "archive")
    os.makedirs(arch, exist_ok=True)
    if len(rows) >= 10:
        import shutil
        shutil.copy(md, os.path.join(arch, f"测试执行记录_{stamp}.md"))
        shutil.copy(html, os.path.join(arch, f"测试执行记录_{stamp}.html"))
    s = {PASS: 0, FAIL: 0, WARN: 0, SKIP: 0}
    for r in rows:
        s[r.status] = s.get(r.status, 0) + 1
    print(f"\n[汇总] 用例 {len(rows)} 条 | 通过 {s[PASS]} | 失败 {s[FAIL]} "
          f"| 提示 {s[WARN]} | 跳过 {s[SKIP]}")
    print(f"[报告] {md}")
    print(f"[报告] {html}")
