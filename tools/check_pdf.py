"""极简 PDF 结构校验：xref 偏移是否都指向正确的对象、页数是否对得上。

没有第三方 PDF 库时用这个确认自研 PDF 写出器没写坏（浏览器/阅读器打不开，
最常见的原因就是 xref 偏移错位）。
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys


def check(path: pathlib.Path) -> int:
    raw = path.read_bytes()
    problems: list[str] = []

    if not raw.startswith(b"%PDF-1.4"):
        problems.append("文件头不是 %PDF-1.4")
    if not raw.rstrip().endswith(b"%%EOF"):
        problems.append("文件尾缺 %%EOF")

    m = re.search(rb"startxref\s+(\d+)\s+%%EOF", raw)
    if not m:
        print("找不到 startxref")
        return 1
    xref_at = int(m.group(1))
    lines = raw[xref_at:].split(b"\n")
    if lines[0].strip() != b"xref":
        problems.append(f"startxref 指向 {xref_at}，但那里不是 'xref'")
        print("\n".join(problems))
        return 1
    try:
        start, count = (int(x) for x in lines[1].split()[:2])
    except Exception:
        print("xref 头无法解析：", lines[1][:40])
        return 1

    entries = lines[2:2 + count]
    ok = 0
    for i in range(count):
        line = entries[i].strip()
        if not line:
            problems.append(f"第 {i} 条 xref 为空")
            continue
        parts = line.split()
        off, _gen, kind = int(parts[0]), parts[1], parts[2]
        if kind == b"f":
            continue
        prefix = f"{i} 0 obj".encode()
        if raw[off:off + len(prefix)] != prefix:
            problems.append(f"对象 {i} 偏移 {off} 处不是 '{prefix.decode()}'")
        else:
            ok += 1

    kids = re.search(rb"/Type /Pages /Kids \[([^\]]*)\] /Count (\d+)", raw)
    n_kids = len(kids.group(1).split(b"R")) - 1 if kids else 0
    n_count = int(kids.group(2)) if kids else 0
    n_img = len(re.findall(rb"/Subtype /Image", raw))
    if n_kids != n_count:
        problems.append(f"/Kids 数量 {n_kids} 与 /Count {n_count} 不一致")
    if n_img != n_count:
        problems.append(f"图片对象 {n_img} 个与页数 {n_count} 不一致")

    print(f"文件      {path.name}  {len(raw) / 1024:.0f} KB")
    print(f"对象      {count - 1} 个（有效偏移 {ok} 个）")
    print(f"页数      {n_count}，内嵌图片 {n_img} 张")
    if problems:
        print("问题：")
        for p in problems:
            print("  -", p)
        return 1
    print("结构校验通过")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    sys.exit(check(pathlib.Path(ap.parse_args().pdf)))
