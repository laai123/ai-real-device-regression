# -*- coding: utf-8 -*-
"""校验 allure 报告产物是否完整、可信。"""
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    rd = os.path.join(ROOT, "reports", "allure-report")
    print("=== allure 报告产物 ===")
    for p in ["data/suites.json", "data/behaviors.json", "data/categories.json",
              "index.html", "app.js"]:
        f = os.path.join(rd, p)
        print(f"  {p:<26} {'OK ' + str(os.path.getsize(f)) + 'B' if os.path.exists(f) else '缺失'}")

    b = os.path.join(rd, "data", "behaviors.json")
    if os.path.exists(b):
        d = json.load(open(b, encoding="utf-8"))
        feats = d.get("children", [])
        print(f"\n=== 按 feature 分组（共 {len(feats)} 组）===")
        for f in feats:
            print(f"  {f.get('name')}: {len(f.get('children', []))} 条")

    print("\n=== 原始数据 ===")
    print("  结果 json:", len(glob.glob(os.path.join(ROOT, "allure-results", "*-result.json"))))
    print("  附件     :", len(glob.glob(os.path.join(ROOT, "allure-results", "*-attachment*"))))
    env = os.path.join(ROOT, "allure-results", "environment.properties")
    if os.path.exists(env):
        print("\n=== 环境信息（会显示在报告首页）===")
        print(open(env, encoding="utf-8").read().strip())


if __name__ == "__main__":
    main()
