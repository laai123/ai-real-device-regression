# -*- coding: utf-8 -*-
"""显式等待（explicit wait）：轮询直到条件成立，成立就立刻返回。

项目规范要求「禁止硬等待，必须用显式等待」，所以整个套件里**不再用 time.sleep
做同步**，需要等某个状态时一律调用这里的 poll/until。

为什么重要：本设备上一次 `uiautomator dump` 约 2.4 秒，而 `dumpsys window`
只要 0.18 秒。所以：
  - 等「界面切换」这类便宜信号 → 用 focus 系列（快）
  - 等「某个元素出现 / 文字变化」→ 才用 ui 系列（贵，但一次到位）
固定睡眠既慢又不可靠；轮询则"条件一成立立刻继续"。
"""
import time

DEFAULT_TIMEOUT = 12.0
FAST_INTERVAL = 0.15
UI_INTERVAL = 0.25


class WaitTimeout(AssertionError):
    """等待超时。继承 AssertionError，让 pytest 把它当成断言失败而不是用例报错。"""


def until(pred, timeout=DEFAULT_TIMEOUT, interval=FAST_INTERVAL, desc="条件",
          swallow=(Exception,)):
    """轮询直到 pred() 返回真值，返回该真值；超时抛 WaitTimeout。

    pred 抛出的异常默认被忽略（界面在切换过程中读不全是常事），
    只把最后一次异常记在超时信息里，方便排查。
    """
    deadline = time.monotonic() + timeout
    last_err = None
    while True:
        try:
            value = pred()
            if value:
                return value
        except swallow as e:          # noqa: PERF203
            last_err = e
        if time.monotonic() >= deadline:
            extra = f"（最后一次异常：{last_err!r}）" if last_err else ""
            raise WaitTimeout(f"等待超时 {timeout:g}s：{desc}{extra}")
        time.sleep(interval)


def sleep(seconds):
    """仅用于「无任何可观测条件」的场景（例如等物理动画）。
    正常同步请用 until()。"""
    time.sleep(seconds)


class Stopwatch:
    """给报告用的计时器：统计每个阶段花了多久。"""

    def __init__(self):
        self.marks = []

    def mark(self, name):
        self.marks.append((name, time.monotonic()))
        return self

    def report(self):
        out = []
        for i in range(1, len(self.marks)):
            out.append((self.marks[i][0],
                        round(self.marks[i][1] - self.marks[i - 1][1], 2)))
        return out
