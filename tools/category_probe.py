# -*- coding: utf-8 -*-
"""列出每个分类标签下的实际菜名，与菜谱数据里的 cuisine 做 diff。"""
import os
import sys
import re
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kitchen_test import device as D
from kitchen_test import pages as P


def dishes_under(label, max_scroll=40):
    P.go_home()
    P.open_recipe_list()
    if not P.click_category(label):
        return None
    names = []
    for _ in range(max_scroll):
        ui = D.dump_ui()
        for t in P.visible_dish_list(ui):
            if t not in names:
                names.append(t)
        before = [n.text for n in ui.nodes]
        D.swipe(540, 1780, 540, 1300, 350, 0.4)
        if before == [n.text for n in D.dump_ui().nodes]:
            break
    return names


def main():
    recs = P.load_recipes_local()
    labels = ["川菜", "湘菜", "粤菜", "家常菜", "日料", "西餐", "韩餐", "东南亚/闽菜"]
    for label in labels:
        got = dishes_under(label)
        if got is None:
            print(f"### {label}: 标签点不到")
            continue
        if label == "东南亚/闽菜":
            exp = {n for n, d in recs.items() if d.get("cuisine") in ("东南亚", "闽菜")}
        else:
            exp = {n for n, d in recs.items() if d.get("cuisine") == label}
        got_s = set(got)
        print(f"### {label}  界面 {len(got)} / 数据 {len(exp)}")
        extra = got_s - exp
        miss = exp - got_s
        if extra:
            for n in sorted(extra):
                print(f"    + 界面有但数据不是该菜系: {n} "
                      f"(数据 cuisine={recs.get(n, {}).get('cuisine')})")
        if miss:
            for n in sorted(miss):
                print(f"    - 界面缺: {n} (数据 cuisine={recs.get(n, {}).get('cuisine')})")


if __name__ == "__main__":
    main()
