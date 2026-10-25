# -*- coding: utf-8 -*-
"""实测 input swipe 在菜谱列表里的"实际滚动距离"，用来选安全又高效的步长。

原理：记录某个菜名在滑动前后的 y 坐标，差值就是实际滚动像素。
若实际滚动远大于手指位移，说明触发了惯性甩动——会跳过条目，不能用。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kitchen_test import device as D
from kitchen_test import pages as P


def dish_map(u):
    """列表里可见的 {菜名: y}。"""
    out = {}
    for n in u.nodes:
        if n.text and n.center and n.center[1] > 560 and n.center[0] > 400 \
                and n.cls.endswith("TextView") \
                and "\n" not in n.text and "★" not in n.text \
                and not n.text.startswith("⏱"):
            out.setdefault(n.text, n.center[1])
    return out


def measure(distance, ms):
    P.go_home()
    P.open_recipe_list()
    before = dish_map(D.ui())
    D.shell(f"input swipe 540 1850 540 {1850 - distance} {ms}")
    D.invalidate()
    after = dish_map(D.ui())
    common = set(before) & set(after)
    if not common:
        return len(before), len(after), None, None
    deltas = [before[k] - after[k] for k in common]
    delta = sum(deltas) / len(deltas)
    return len(before), len(after), delta, delta / distance


def main():
    print(f"{'手指位移':>8} {'时长':>6} {'实际滚动':>9} {'放大倍数':>9}  说明")
    for distance, ms in [(500, 300), (900, 400), (1250, 350),
                         (1400, 800), (1600, 350), (1600, 900),
                         (1800, 1200)]:
        nb, na, delta, ratio = measure(distance, ms)
        if delta is None:
            print(f"{distance:>8} {ms:>6} {'—':>9} {'—':>9}  "
                  f"两帧无共同条目（可见{nb}->{na}）")
            continue
        note = "安全（位移可预期）" if ratio < 1.4 else "★甩动过大，会跳过条目"
        print(f"{distance:>8} {ms:>6} {delta:>9.0f} {ratio:>9.2f}  {note}")


if __name__ == "__main__":
    main()
