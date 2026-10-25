# -*- coding: utf-8 -*-
"""把 adb uiautomator dump 出来的 XML 精简成人能看的列表。"""
import sys
import re
import xml.etree.ElementTree as ET


def parse_bounds(b):
    m = re.findall(r"-?\d+", b or "")
    if len(m) != 4:
        return None
    x1, y1, x2, y2 = map(int, m)
    return x1, y1, x2, y2


def center(b):
    if not b:
        return None
    x1, y1, x2, y2 = b
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def walk(node, depth, out):
    a = node.attrib
    text = (a.get("text") or "").strip()
    desc = (a.get("content-desc") or "").strip()
    rid = (a.get("resource-id") or "").strip()
    cls = (a.get("class") or "").strip().rsplit(".", 1)[-1]
    b = parse_bounds(a.get("bounds"))
    c = center(b)
    flags = []
    if a.get("clickable") == "true":
        flags.append("click")
    if a.get("scrollable") == "true":
        flags.append("scroll")
    if a.get("checkable") == "true":
        flags.append("checkable")
    if a.get("checked") == "true":
        flags.append("CHECKED")
    if a.get("enabled") == "false":
        flags.append("DISABLED")
    if a.get("selected") == "true":
        flags.append("sel")
    if a.get("password") == "true":
        flags.append("pwd")
    if a.get("focusable") == "true" and cls in ("EditText", "AutoCompleteTextView"):
        flags.append("focus")

    if text or desc or rid or flags:
        line = "  " * depth + f"<{cls}>"
        if text:
            line += f' text="{text}"'
        if desc:
            line += f' desc="{desc}"'
        if rid:
            line += f" id={rid}"
        if c:
            line += f" @{c[0]},{c[1]} {b}"
        if flags:
            line += " [" + ",".join(flags) + "]"
        out.append(line)

    for ch in node:
        walk(ch, depth + 1, out)


def main(path):
    tree = ET.parse(path)
    out = []
    walk(tree.getroot(), 0, out)
    print("\n".join(out))
    print(f"\n--- {len(out)} 个有效节点 ---")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ui.xml")
