# -*- coding: utf-8 -*-
"""pytest 用例入口：把 kitchen_test 里注册的用例逐条跑成独立的测试项。

为什么用 parametrize 而不是把 37 条用例重写一遍：
用例的实现（cases_data.py / cases_ui.py）是"检查逻辑"，与"用什么跑"无关。
这里只做一层薄适配——把每条用例变成一个 pytest 测试项，并挂上 allure 的
feature / story / severity / 附件。这样：
  - 逻辑只需维护一份；
  - 报告里每条用例独立可见、可单独重跑（pytest tests -k D2）。
"""
import time

import pytest

from kitchen_test import framework as F

SEV = {
    "P0": "blocker",      # allure 的等级名
    "P1": "critical",
    "P2": "normal",
    "P3": "minor",
}


def _allure_severity(sev):
    try:
        import allure
        m = {"P0": allure.severity_level.BLOCKER,
             "P1": allure.severity_level.CRITICAL,
             "P2": allure.severity_level.NORMAL,
             "P3": allure.severity_level.MINOR}
        return m.get(sev, allure.severity_level.NORMAL)
    except Exception:
        return None


@pytest.mark.parametrize(
    "cid,title,group,severity,fn", F.CASES, ids=[c[0] for c in F.CASES])
def test_case(cid, title, group, severity, fn):
    """执行一条用例。失败时的证据挂载在 conftest 的钩子里统一处理。"""
    import allure
    from tests import conftest as cf

    allure.dynamic.feature(group)
    allure.dynamic.story(f"[{severity}] {title}")
    allure.dynamic.title(f"{cid} {title}")
    allure.dynamic.label("case_id", cid)
    allure.dynamic.label("severity_class", severity)
    sev = _allure_severity(severity)
    if sev is not None:
        allure.dynamic.severity(sev)

    res = F.CaseResult(cid, title, group, severity)
    cf.RESULTS[cid] = res
    t0 = time.time()
    try:
        fn(None, res)
    finally:
        res.elapsed = time.time() - t0
        for i, note in enumerate(res.notes, 1):
            allure.attach(str(note), name=f"用例记录 {i}",
                          attachment_type=allure.attachment_type.TEXT)
        if res.status == "WARN":
            allure.attach(res.detail or "", name="提示级观察（不计为缺陷）",
                          attachment_type=allure.attachment_type.TEXT)
