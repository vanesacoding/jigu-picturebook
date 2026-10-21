"""端到端冒烟：上传照片 → 预览故事 → 建书 → 真实生成 → 检查产物。

用途有两个：
1. 开发自测：一条命令确认整条链路可跑通。
2. 复现第一本小书：《我是国王先生！》

  python tools/e2e_test.py --photos a.jpg b.jpg --preset king
  python tools/e2e_test.py --base http://127.0.0.1:7860 --no-generate   # 只验接口，不花钱
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

import requests

DEFAULT_BASE = "http://127.0.0.1:7860"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--photos", nargs="+", required=True)
    ap.add_argument("--preset", default="king")
    ap.add_argument("--event", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--no-generate", action="store_true")
    ap.add_argument("--regen", type=int, default=0, help="生成后重画第 N 页")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--timeout", type=int, default=420)
    args = ap.parse_args()

    base = args.base.rstrip("/")

    h = requests.get(f"{base}/api/health", timeout=60).json()
    print(f"[1/7] 健康检查  模型={h['model']} 可用={h['model_ok']} 已花 ¥{h['spent_cny']}")
    if not h["model_ok"]:
        print("      模型不可用：", h["model_error"])
        return 2

    files = [("photos", (pathlib.Path(p).name, open(p, "rb"), "image/jpeg")) for p in args.photos]
    r = requests.post(f"{base}/api/uploads", files=files, timeout=120).json()
    for _, (_, fh, _) in files:
        fh.close()
    if not r.get("ok"):
        print("      上传失败：", r.get("error"))
        return 2
    photo_ids = [p["id"] for p in r["photos"]]
    print(f"[2/7] 上传照片  {len(photo_ids)} 张  {[p['url'] for p in r['photos']]}")

    preset = requests.get(f"{base}/api/preset/{args.preset}", timeout=30).json().get("preset", {})
    body = {
        "event": args.event or preset.get("event", ""),
        "feeling": preset.get("feeling", ""),
        "detail": preset.get("detail", ""),
        "child_name": args.name or preset.get("child_name", ""),
        "preset": args.preset,
    }
    d = requests.post(f"{base}/api/story/preview", json=body, timeout=60).json()
    if not d.get("ok"):
        print("      预览失败：", d.get("error"))
        return 2
    draft = d["draft"]
    print(f"[3/7] 故事预览  {draft['title']} / {draft['subtitle']}  preset={d.get('from_preset')}")
    for i, p in enumerate(draft["pages"], 1):
        print(f"        P{i} {p['text']}")

    payload = {
        "title": draft["title"],
        "subtitle": draft["subtitle"],
        "child_name": body["child_name"] or "宝宝",
        "event": body["event"],
        "feeling": body["feeling"],
        "detail": body["detail"],
        "character": draft["character"],
        "pages": draft["pages"],
        "photo_ids": photo_ids,
    }
    made = requests.post(f"{base}/api/books", json=payload, timeout=60).json()
    if not made.get("ok"):
        print("      建书失败：", made.get("error"))
        return 2
    book_id = made["book"]["id"]
    print(f"[4/7] 建书      {book_id}  角色={draft['character']}")

    if args.no_generate:
        print("      已跳过生成（--no-generate）")
        return 0

    g = requests.post(f"{base}/api/books/{book_id}/generate", json={}, timeout=60).json()
    if not g.get("ok"):
        print("      启动生成失败：", g.get("error"))
        return 2
    print("[5/7] 开始生成  逐页调用 Seedream，等待……")

    t0 = time.time()
    book = {}
    while time.time() - t0 < args.timeout:
        time.sleep(2)
        book = requests.get(f"{base}/api/books/{book_id}", timeout=60).json()["book"]
        states = " ".join(f"P{p['idx']}:{p['status']}" for p in book["pages"])
        print(f"      {int(time.time() - t0):>3}s {states}")
        if not book.get("generating"):
            break
    done = [p for p in book.get("pages", []) if p.get("image_url")]
    print(f"[6/7] 生成完成  {len(done)}/5 页  状态={book.get('status')}  费用 ¥{book.get('cost_cny')}")

    for p in book.get("pages", []):
        note = f"  {p['error'][:80]}" if p.get("error") else ""
        print(f"        P{p['idx']} {p['status']:<8} {p.get('image_url', '')}{note}")

    if args.regen:
        print(f"[7/7] 重画第 {args.regen} 页……")
        rr = requests.post(
            f"{base}/api/books/{book_id}/pages/{args.regen}/regenerate",
            json={"feedback": "variation"}, timeout=420,
        ).json()
        print("      结果：", "成功" if rr.get("ok") else rr.get("error"))

    if args.export:
        e = requests.get(f"{base}/api/books/{book_id}/export", timeout=300)
        out = pathlib.Path(__file__).resolve().parent.parent / "data" / "tmp" / f"export_{book_id}.zip"
        out.write_bytes(e.content)
        print(f"      导出 {e.status_code} -> {out} ({out.stat().st_size // 1024} KB)")

    print(f"\n阅读页：{base}/#/read/{book_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
