# -*- coding: utf-8 -*-
"""数据驱动地走完一道菜的助手模式。

步骤与选项名都从菜谱 JSON 取，界面只负责"照名字点"，避免靠坐标猜。

用法: python tools/run_one.py 麻婆豆腐
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kitchen_test import device as D
from kitchen_test import pages as P

RECIPES = P.load_recipes_local()


def close_dialog():
    ui = D.dump_ui()
    if ui.by_id("alertTitle"):
        title = ui.by_id("alertTitle").text
        for n in ui.nodes:
            if n.text in ("知道了", "取消"):
                D.tap(*n.center)
                time.sleep(1.2)
                return title
    return None


def step1_names(recipe):
    """第1步要选的选项名：每个食材的每个选项组取第一项（跳过空 options）。"""
    names, skipped = [], []
    for ing in (recipe.get("ingredients") or {}).values():
        opts = ing.get("options") or {}
        if not opts:
            skipped.append(ing.get("name"))
            continue
        for ov in opts.values():
            olist = (ov or {}).get("options") or []
            if olist:
                names.append(olist[0]["name"])
            else:
                skipped.append(ing.get("name"))
    return names, skipped


def flow_first_option(recipe, step_name):
    """按步骤名找到流程步骤，取其第一项选项名。"""
    for k, v in (recipe.get("cooking_flow") or {}).items():
        if v.get("name") == step_name:
            olist = v.get("options") or []
            return olist[0]["name"] if olist else None, k, len(olist)
    return None, None, 0


def main():
    dish = sys.argv[1] if len(sys.argv) > 1 else "麻婆豆腐"
    recipe = RECIPES[dish]
    exp_flow = [v["name"] for v in (recipe.get("cooking_flow") or {}).values()]
    print(f"数据中烹饪流程({len(exp_flow)}步): {exp_flow}")

    P.go_home()
    P.open_recipe_list()
    ok, sc, _ = P.open_dish_by_name(dish)
    print(f"列表定位: {ok} (滚动{sc}次)")
    P.choose_mode("助手模式")
    time.sleep(1.8)
    d = close_dialog()
    if d:
        print(f"  ⚠ 弹窗: {d}")

    seen_steps = []
    for i in range(10):
        ui = D.dump_ui()
        s = P.cooking_snapshot(ui)
        if not s.get("progress"):
            print("离开烹饪页:", D.current_focus())
            break
        title = (s["step_title"] or "").replace("🤖", "").strip()
        title = title.split("：")[-1]          # "第2步：炒肉末" -> "炒肉末"
        seen_steps.append(title)
        if i == 0:
            names, skipped = step1_names(recipe)
            left = P.select_options_by_names(names)
            print(f"  第1步 食材准备 | 应选 {names} | 未点到 {left or '无'}"
                  f" | 无可选项食材 {skipped or '无'}")
        else:
            nm, key, cnt = flow_first_option(recipe, title)
            left = P.select_options_by_names([nm])
            print(f"  第{i+1}步 {title} | 数据键={key} 选项数={cnt} "
                  f"| 点选={nm} | 未点到 {left or '无'}")
        ui = D.dump_ui()
        btn = ui.by_id("btn_next")
        if not btn:
            break
        D.tap(*btn.center)
        time.sleep(1.4)
        d = close_dialog()
        if d:
            print(f"  ⚠ 弹窗: {d}")
        ui = D.dump_ui()
        if ui.by_id("tv_total_score"):
            r = P.read_result(ui)
            tot = 0
            print(f"  结果页 总分={r['total']} 等级={r['level']}")
            for name, val in r["items"]:
                a, _ = val.split("/")
                tot += int(a)
                print(f"      {name} = {val}")
            print(f"      单项之和={tot} / 总分={r['total']}")
            break

    print(f"界面实际呈现 {len(seen_steps)} 个步骤: {seen_steps}")
    missing = [n for n in exp_flow if n not in seen_steps]
    print(f"数据里有但界面没呈现的步骤({len(missing)}): {missing}")


if __name__ == "__main__":
    main()
