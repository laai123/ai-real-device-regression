# -*- coding: utf-8 -*-
"""对导出的菜谱/配置数据做一致性校验，找出数据层面的缺陷。

用法: python tools/data_audit.py
输入: data_dump/appdata/  (由 tools/pull_appdata.py 导出)
输出: 控制台摘要 + reports/data_audit.json
"""
import json
import os
import glob
import collections

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(PROJ, "data_dump", "appdata")

SCORE_KEYS = ["knife_skills", "heat_control", "seasoning",
              "step_order", "time_efficiency", "creativity"]
SCORE_CN = {
    "knife_skills": "刀工处理", "heat_control": "火候控制",
    "seasoning": "调味逻辑", "step_order": "步骤顺序",
    "time_efficiency": "时间效率", "creativity": "创意搭配",
}


def load_recipes():
    out = {}
    for p in sorted(glob.glob(os.path.join(DATA, "recipes", "*.json"))):
        with open(p, encoding="utf-8") as fh:
            try:
                out[os.path.basename(p)[:-5]] = json.load(fh)
            except json.JSONDecodeError as e:
                out[os.path.basename(p)[:-5]] = {"__error__": str(e)}
    return out


def collect_issues(recipes, config):
    issues = []

    def add(sev, rid, cat, msg, extra=None):
        issues.append({"severity": sev, "recipe": rid, "category": cat,
                       "message": msg, "extra": extra or {}})

    seen_names = collections.Counter()
    ids = collections.Counter()

    for rid, d in recipes.items():
        if "__error__" in d:
            add("P0", rid, "数据格式", f"JSON 解析失败: {d['__error__']}")
            continue
        seen_names[rid] += 1

        # ---------- 1. 评分满分是否合计 100 ----------
        sc = d.get("scoring", {})
        total = sum(sc.get(k, 0) for k in SCORE_KEYS)
        if total != 100:
            add("P1", rid, "评分逻辑",
                f"评分满分合计为 {total}，不是 100 分（{sc}）", {"total": total})
        missing = [k for k in SCORE_KEYS if k not in sc]
        if missing:
            add("P1", rid, "评分逻辑", f"缺少评分维度: {missing}")

        # ---------- 2. 食材 options 是否为空 ----------
        for ing_key, ing in (d.get("ingredients") or {}).items():
            if not isinstance(ing, dict):
                continue
            opts = ing.get("options")
            if opts is None:
                add("P1", rid, "食材数据",
                    f"食材「{ing.get('name', ing_key)}」缺少 options 字段")
            elif isinstance(opts, dict) and len(opts) == 0:
                add("P0", rid, "食材数据",
                    f"食材「{ing.get('name', ing_key)}」的 options 为空对象，"
                    f"界面会只显示名称、无任何可选项，用户无法选择",
                    {"ingredient": ing.get("name")})
            elif isinstance(opts, dict):
                for ok, ov in opts.items():
                    olist = (ov or {}).get("options") or []
                    if not olist:
                        add("P0", rid, "食材数据",
                            f"食材「{ing.get('name')}」下的「{ov.get('label', ok)}」"
                            f"没有任何选项")
                    for o in olist:
                        if "id" in o:
                            ids[o["id"]] += 1

        # ---------- 3. 每步选项是否为空 ----------
        flow = d.get("cooking_flow") or {}
        if not flow:
            add("P1", rid, "流程数据", "cooking_flow 为空")
        for fk, fv in flow.items():
            olist = (fv or {}).get("options") or []
            if not olist:
                add("P0", rid, "流程数据",
                    f"步骤「{(fv or {}).get('name', fk)}」没有任何可选项")
            for o in olist:
                if "id" in o:
                    ids[o["id"]] += 1

        # ---------- 4. standard_answers 引用的 id 是否存在 ----------
        all_ids = set()
        for ing in (d.get("ingredients") or {}).values():
            for ov in (ing.get("options") or {}).values():
                for o in (ov or {}).get("options") or []:
                    if "id" in o:
                        all_ids.add(o["id"])
        for fv in flow.values():
            for o in (fv or {}).get("options") or []:
                if "id" in o:
                    all_ids.add(o["id"])

        sa = d.get("standard_answers") or {}
        sa_ids = []
        for group in (sa.get("ingredients") or {}).values():
            if isinstance(group, dict):
                sa_ids += [v for v in group.values() if isinstance(v, str)]
        for v in (sa.get("cooking_flow") or {}).values():
            if isinstance(v, str):
                sa_ids.append(v)
        for sid in sa_ids:
            if sid not in all_ids:
                add("P1", rid, "标准答案",
                    f"standard_answers 引用了不存在的选项 id: {sid}")

        # ---------- 5. 标准答案是否覆盖所有流程步骤 ----------
        miss_flow = [k for k in flow if k not in (sa.get("cooking_flow") or {})]
        if miss_flow:
            add("P1", rid, "标准答案",
                f"cooking_flow 中这些步骤在 standard_answers 里没有标准答案: {miss_flow}")

        # ---------- 6. tips 完整性 ----------
        tips = sa.get("tips") or {}
        for key in ["perfect", "good", "average"]:
            if not tips.get(key):
                add("P2", rid, "文案数据", f"tips 缺少 {key} 文案")
        if "poor" not in tips and "poose" not in tips:
            add("P2", rid, "文案数据", "tips 缺少 low/poose 档位文案（疑似拼写错误）")
        if "poose" in tips:
            add("P3", rid, "文案数据",
                "tips 档位键名拼写为 'poose'，疑似应为 'poor'")

        # ---------- 7. 难度与时间字段 ----------
        diff = d.get("difficulty")
        if not isinstance(diff, int) or not 1 <= diff <= 5:
            add("P2", rid, "字段取值",
                f"difficulty={diff!r} 不在 1..5 范围（界面按 ★ 渲染，共5星）")
        ct = d.get("cook_time")
        ot = sa.get("optimal_time")
        if ct and ot and ct != ot:
            add("P2", rid, "字段一致性",
                f"cook_time={ct} 与 standard_answers.optimal_time={ot} 不一致")
        if not d.get("calories"):
            add("P3", rid, "字段缺失", "缺少 calories 字段")
        if not d.get("servings"):
            add("P3", rid, "字段缺失", "缺少 servings 字段")

        # ---------- 8. 选项分数是否超过该维度满分 ----------
        knife_opts = []
        tofu = (d.get("ingredients") or {}).get("tofu") or {}
        for ov in (tofu.get("options") or {}).values():
            for o in (ov or {}).get("options") or []:
                if isinstance(o.get("score"), (int, float)):
                    knife_opts.append(o["score"])
        if knife_opts and sc.get("knife_skills"):
            # 刀工维度由多个食材选项共同决定，取平均后不应超过满分
            avg = sum(knife_opts) / len(knife_opts)
            if avg > sc["knife_skills"]:
                add("P2", rid, "评分逻辑",
                    f"食材选项平均分 {avg:.1f} 超过刀工满分 {sc['knife_skills']}")

        # ---------- 9. 步骤参数里的时间是否自相矛盾 ----------
        for fk, fv in flow.items():
            for o in (fv or {}).get("options") or []:
                p = o.get("params") or {}
                t = str(p.get("time", ""))
                if t.endswith("分钟"):
                    try:
                        mins = float(t.replace("分钟", ""))
                    except ValueError:
                        continue
                    if mins > 30:
                        add("P2", rid, "参数数据",
                            f"步骤「{fv.get('name')}」选项「{o.get('name')}」"
                            f"耗时 {t} 异常偏长")

    # ---------- 重复 id ----------
    for oid, n in ids.items():
        if n > 1:
            add("P2", "*", "数据重复", f"选项 id 重复出现 {n} 次: {oid}")

    # ---------- 配置 ----------
    prof = (config or {}).get("profile") or {}
    spice_opts = {"不辣", "微辣", "中辣", "重辣"}
    if prof.get("spice_level") and prof["spice_level"] not in spice_opts:
        add("P1", "*", "配置一致性",
            f"user_config.json 中 spice_level='{prof['spice_level']}' "
            f"不在界面辣度可选项 {sorted(spice_opts)} 中，"
            f"会导致界面无法正确回显当前选择")
    if (config or {}).get("user_id") == 0:
        add("P2", "*", "配置一致性",
            "user_config.json 的 user_id=0，而 users.json 中账号 user_id=1，两者不一致")
    return issues


def main():
    recipes = load_recipes()
    cfg_path = os.path.join(DATA, "user_config.json")
    config = {}
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as fh:
            config = json.load(fh)

    issues = collect_issues(recipes, config)

    by_sev = collections.Counter(i["severity"] for i in issues)
    by_cat = collections.Counter(i["category"] for i in issues)

    print(f"菜谱总数: {len(recipes)}")
    print(f"发现问题: {len(issues)} 条  P0={by_sev['P0']} P1={by_sev['P1']} "
          f"P2={by_sev['P2']} P3={by_sev['P3']}")
    print("\n按类别:")
    for c, n in by_cat.most_common():
        print(f"  {c}: {n}")

    print("\n===== P0 / P1 明细 =====")
    for i in issues:
        if i["severity"] in ("P0", "P1"):
            print(f"[{i['severity']}] {i['recipe']} | {i['category']} | {i['message']}")

    os.makedirs(os.path.join(PROJ, "reports"), exist_ok=True)
    out = os.path.join(PROJ, "reports", "data_audit.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"recipe_count": len(recipes), "issues": issues},
                  fh, ensure_ascii=False, indent=2)
    print("\n明细已写入", out)

    # 统计信息，报告里要用
    stat = {
        "菜系分布": collections.Counter(d.get("cuisine") for d in recipes.values()),
        "分类分布": collections.Counter(d.get("category") for d in recipes.values()),
        "难度分布": collections.Counter(d.get("difficulty") for d in recipes.values()),
    }
    print("\n===== 统计 =====")
    for k, v in stat.items():
        print(f"{k}: {dict(v)}")


if __name__ == "__main__":
    main()
