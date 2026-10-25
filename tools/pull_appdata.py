# -*- coding: utf-8 -*-
"""把 app 私有目录 files/data 下的文件全部导出到本地 data_dump/appdata。

依赖：app 必须是 debuggable（可用 run-as）。用于离线核对数据与逻辑。
"""
import os
import subprocess
import sys

PKG = "com.example.kitchenassistant"
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(PROJ, "data_dump", "appdata")


def sh(args):
    p = subprocess.run(["adb", "shell"] + args, capture_output=True)
    return p.stdout


def walk(remote):
    """返回 remote 下所有文件的相对路径。"""
    out = sh(["run-as", PKG, "sh", "-c", f"'cd {remote} && find . -type f'"])
    files = []
    for line in out.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if line.startswith("./"):
            files.append(line[2:])
    return files


def pull(remote, local):
    os.makedirs(os.path.dirname(local), exist_ok=True)
    # exec-out 避免 PTY 的 \r\n 转换
    p = subprocess.run(
        ["adb", "exec-out", "run-as", PKG, "cat", remote], capture_output=True)
    with open(local, "wb") as fh:
        fh.write(p.stdout)
    return len(p.stdout)


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "files/data"
    files = walk(base)
    if not files:
        print("没找到文件，确认 app 是否 debuggable / 路径是否正确")
        return
    total = 0
    for rel in files:
        remote = f"{base}/{rel}"
        local = os.path.join(OUT, rel.replace("\\", "/"))
        n = pull(remote, local)
        total += n
    print(f"导出 {len(files)} 个文件，共 {total} 字节 -> {OUT}")


if __name__ == "__main__":
    main()
