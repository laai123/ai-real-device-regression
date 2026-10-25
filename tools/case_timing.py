# -*- coding: utf-8 -*-
"""从 allure-results 里统计每条用例的耗时，按耗时倒序输出。"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    rows = []
    for f in glob.glob(os.path.join(ROOT, "allure-results", "*-result.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        rows.append((d.get("start", 0), d.get("stop", 0),
                     d.get("name", ""), d.get("status", "")))
    if not rows:
        print("没有 allure-results，请先跑一轮")
        return
    rows.sort(key=lambda r: -(r[1] - r[0]))
    total = sum((e - s) / 1000 for s, e, _, _ in rows)
    print(f"用例耗时排行（合计 {total:.0f} 秒 / {len(rows)} 条）")
    print("-" * 70)
    for s, e, n, st in rows:
        dur = (e - s) / 1000
        print(f"{dur:7.1f}s  {st:<8} {n[:52]}")
    top = sum((e - s) / 1000 for s, e, _, _ in rows[:8])
    print("-" * 70)
    print(f"最慢 8 条合计 {top:.0f} 秒，占 {top / total * 100:.0f}%")


if __name__ == "__main__":
    main()
