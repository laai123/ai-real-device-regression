# -*- coding: utf-8 -*-
"""界面速查小工具：dump / 点击 / 返回，边探索边用。

用法:
  python tools/probe.py dump            抓当前界面并打印
  python tools/probe.py tap 540 609     点击坐标
  python tools/probe.py back            返回
  python tools/probe.py text 退出登录   按文字点击
  python tools/probe.py shot 名字       截图
  python tools/probe.py focus           看当前页面
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kitchen_test import device as D  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "dump":
        ui = D.dump_ui()
        print(ui.dump())
    elif cmd == "tap":
        D.tap(int(sys.argv[2]), int(sys.argv[3]))
        print("点击完成")
    elif cmd == "long":
        D.long_press(int(sys.argv[2]), int(sys.argv[3]))
        print("长按完成")
    elif cmd == "swipe":
        D.swipe(*[int(x) for x in sys.argv[2:6]])
        print("滑动完成")
    elif cmd == "back":
        D.back()
        print("返回完成")
    elif cmd == "text":
        target = sys.argv[2]
        ui = D.dump_ui()
        n = ui.by_text(target)
        if n and n.center:
            D.tap(*n.center)
            print(f"点击 {target!r} @{n.center}")
        else:
            print(f"未找到 {target!r}")
    elif cmd == "shot":
        print(D.screenshot(sys.argv[2]))
    elif cmd == "focus":
        print(D.current_focus())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
