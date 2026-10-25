# -*- coding: utf-8 -*-
"""测试入口：pytest + allure。

用法:
  python run_tests.py                    # 跑全部
  python run_tests.py D1 D2              # 只跑编号含 D1/D2 的用例
  python run_tests.py --no-allure        # 只跑，不生成 allure 报告
  python run_tests.py -k 分类            # 关键字过滤（透传给 pytest）

流程：pytest 执行用例 → 产出 allure-results（原始数据）→ allure 命令行生成
HTML 报告（目录版 + 单文件版）。同时 conftest 会汇总出 Markdown/HTML 记录。
"""
import os
import sys
import shutil
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

ALLURE_HOME_CANDIDATES = [
    r"E:\allure-2.46.1",
    r"D:\迅雷下载\allure-2.46.1\allure-2.46.1",
    os.environ.get("ALLURE_HOME", ""),
]
JAVA_HOME_CANDIDATES = [
    os.environ.get("JAVA_HOME", ""),
    r"F:\android studio\jbr",
    r"C:\Program Files\Java\jdk-21",
]


def find_allure():
    for base in ALLURE_HOME_CANDIDATES:
        if base and os.path.exists(os.path.join(base, "bin", "allure.bat")):
            return os.path.join(base, "bin", "allure.bat")
    return shutil.which("allure")


def find_java_home():
    for base in JAVA_HOME_CANDIDATES:
        if base and os.path.exists(os.path.join(base, "bin", "java.exe")):
            return base
    return None


def run_allure(results_dir, report_dir, single_dir):
    """生成 allure HTML 报告。

    产出两份：
      reports/allure-report/index.html         目录版（本地静态服务打开更快）
      reports/allure-report-single/index.html  单文件版（3MB 左右，双击即可看）
    注意：allure 的 -o 始终按"目录"处理，所以单文件版也是放在一个目录里。
    """
    allure = find_allure()
    if not allure:
        print("[allure] 没找到 allure 命令行，跳过 HTML 报告。"
              "可设置环境变量 ALLURE_HOME 指向解压目录。")
        return None, None
    java_home = find_java_home()
    env = dict(os.environ)
    if java_home:
        env["JAVA_HOME"] = java_home

    out_dir = os.path.join(ROOT, "reports", report_dir)
    print(f"[allure] 生成目录版报告 -> {os.path.join(out_dir, 'index.html')}")
    p = subprocess.run([allure, "generate", results_dir, "-o", out_dir, "--clean"],
                       env=env, capture_output=True, text=True)
    if p.returncode != 0:
        print("[allure] 生成失败:\n", (p.stdout or "")[-800:], (p.stderr or "")[-800:])
        return None, None

    single = os.path.join(ROOT, "reports", single_dir)
    print(f"[allure] 生成单文件报告 -> {os.path.join(single, 'index.html')}")
    p2 = subprocess.run([allure, "generate", results_dir, "-o", single, "--clean",
                         "--single-file"], env=env, capture_output=True, text=True)
    if p2.returncode != 0:
        print("[allure] 单文件版生成失败（目录版仍可用）")
        single = None
    return out_dir, single


def main():
    args = sys.argv[1:]
    with_allure = "--no-allure" not in args
    args = [a for a in args if a != "--no-allure"]

    case_ids = [a for a in args if not a.startswith("-")]
    passthrough = [a for a in args if a.startswith("-")]

    results_dir = os.path.join(ROOT, "allure-results")
    if os.path.isdir(results_dir):
        shutil.rmtree(results_dir, ignore_errors=True)
    os.makedirs(results_dir, exist_ok=True)
    os.environ["ALLURE_RESULTS_DIR"] = results_dir

    pytest_args = ["tests", f"--alluredir={results_dir}"] + passthrough
    if case_ids:
        # 用精确的 node id 选择，避免 -k 的子串误伤（例如 I1 会把 I10 也带上）
        pytest_args = [f"tests/test_suite.py::test_case[{c}]" for c in case_ids] \
            + [f"--alluredir={results_dir}"] + passthrough

    print("=" * 66)
    print("厨房小能手 自动化测试  (pytest + allure)")
    print("=" * 66)
    import pytest
    code = pytest.main(pytest_args)

    if with_allure:
        run_allure(results_dir, "allure-report", "allure-report-single")
    return code


if __name__ == "__main__":
    sys.exit(main())
