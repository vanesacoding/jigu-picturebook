"""Flask 路由：上传、故事预览、生成、阅读、重画、导出、删除。

隐私约定：
- 图片只经本地服务发出（127.0.0.1），不外链、不公开。
- 上传时统一重编码为 JPEG，自动丢弃 EXIF（含 GPS/设备信息）。
- 接口不返回任何密钥信息；健康检查只回报模型可用性。
"""

from __future__ import annotations

import io
import pathlib
import uuid

from flask import Blueprint, jsonify, request, send_file, send_from_directory
from PIL import Image

from . import compose, config, db, presets, story, worker

api = Blueprint("api", __name__)

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp"}
MAX_UPLOAD_SIDE = 2400
FEEDBACKS = {"unlike", "scene", "variation"}


def _err(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code


def _book_json(book: dict) -> dict:
    pages = []
    for p in sorted(book.get("pages") or [], key=lambda x: x["idx"]):
        pages.append({
            "idx": p["idx"],
            "text": p["text"],
            "scene": p["scene"],
            "status": p["status"],
            "error": p["error"],
            "redraws": p["redraws"],
            "image_url": f"/api/media/{book['id']}/{p['image']}" if p["image"] else "",
            "versions": p.get("versions") or [],
        })
    return {
        "id": book["id"],
        "title": book["title"],
        "subtitle": book["subtitle"],
        "child_name": book["child_name"],
        "status": book["status"],
        "model": book["model"],
        "cost_cny": book["cost_cny"],
        "error": book["error"],
        "created_at": book["created_at"],
        "event": book["event"],
        "feeling": book["feeling"],
        "detail": book["detail"],
        "character": book["character"],
        "pages": pages,
        "photos": [{"id": u["id"], "url": f"/api/media/up/{u['file']}"} for u in book.get("photos") or []],
    }


# ---------------------------------------------------------------------------
# 基础信息
# ---------------------------------------------------------------------------
@api.get("/health")
def health():
    status = worker.model_status()
    return jsonify({
        "ok": True,
        "model": status.get("model") or config.DEFAULT_MODEL,
        "model_ok": status.get("ok", False),
        "model_error": status.get("error", ""),
        "probe": status.get("probe", {}),
        "spent_cny": round(db.spent_total(), 4),
        "budget_cny": config.APP_BUDGET_CNY,
        "page_count": config.PAGE_COUNT,
        "max_photos": config.MAX_PHOTOS,
    })


@api.get("/preset/<name>")
def get_preset(name: str):
    p = presets.PRESETS.get(name)
    if not p:
        return _err("没有这个示例", 404)
    return jsonify({"ok": True, "preset": p})


# ---------------------------------------------------------------------------
# 照片上传（EXIF 已被剥离）
# ---------------------------------------------------------------------------
@api.post("/uploads")
def upload():
    files = request.files.getlist("photos")
    if not files:
        return _err("没有收到照片")
    if len(files) > config.MAX_PHOTOS:
        return _err(f"一次最多 {config.MAX_PHOTOS} 张照片")

    out = []
    for f in files:
        ext = pathlib.Path(f.filename or "").suffix.lower()
        if ext and ext not in ALLOWED_EXT:
            return _err(f"不支持的文件类型：{ext}")
        try:
            img = Image.open(io.BytesIO(f.read()))
            img.load()
        except Exception:
            return _err("有一张照片无法读取，请换一张试试")
        img = _sanitize(img)
        name = f"{uuid.uuid4().hex[:12]}.jpg"
        config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        img.save(config.UPLOAD_DIR / name, format="JPEG", quality=92)
        up_id = db.add_upload("_pending", name, f.filename or "", img.width, img.height)
        out.append({"id": up_id, "url": f"/api/media/up/{name}", "width": img.width, "height": img.height})
    return jsonify({"ok": True, "photos": out})


def _sanitize(img: Image.Image) -> Image.Image:
    """重编码丢 EXIF / 透明通道，并限制最长边，避免手机原图过大。"""
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_UPLOAD_SIDE:
        scale = MAX_UPLOAD_SIDE / max(w, h)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    # 重新生成一张干净图，不携带任何 exif/icc
    clean = Image.new("RGB", img.size, (255, 255, 255))
    clean.paste(img, (0, 0))
    return clean


@api.delete("/uploads/<up_id>")
def delete_upload(up_id: str):
    up = db.delete_upload(up_id)
    if not up:
        return _err("照片不存在", 404)
    try:
        (config.UPLOAD_DIR / up["file"]).unlink(missing_ok=True)
    except Exception:
        pass
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# 故事预览（不落库、不花钱）
# ---------------------------------------------------------------------------
@api.post("/story/preview")
def preview():
    data = request.get_json(silent=True) or {}
    event = (data.get("event") or "").strip()
    if not event:
        return _err("请先说说今天发生了什么")
    if len(event) > 500:
        return _err("故事描述太长了，请控制在 500 字以内")
    preset = presets.PRESETS.get((data.get("preset") or "").strip())
    if preset:
        return jsonify({
            "ok": True,
            "draft": {
                "title": preset["title"],
                "subtitle": preset["subtitle"],
                "character": preset["character"],
                "pages": preset["pages"],
            },
            "from_preset": True,
        })
    draft = story.structure(
        event=event,
        feeling=(data.get("feeling") or "").strip(),
        detail=(data.get("detail") or "").strip(),
        name=(data.get("child_name") or "").strip() or "宝宝",
    )
    return jsonify({"ok": True, "draft": draft, "from_preset": False})


# ---------------------------------------------------------------------------
# 小书 CRUD
# ---------------------------------------------------------------------------
@api.post("/books")
def create_book():
    data = request.get_json(silent=True) or {}
    event = (data.get("event") or "").strip()
    pages = data.get("pages") or []
    if not event:
        return _err("请先说说今天发生了什么")
    if len(pages) != config.PAGE_COUNT:
        return _err(f"需要正好 {config.PAGE_COUNT} 页内容")

    name = (data.get("child_name") or "").strip() or "宝宝"
    model, _probe = worker.current_model()
    book_id = db.create_book(
        title=(data.get("title") or "").strip() or "《宝宝的小故事》",
        subtitle=(data.get("subtitle") or "").strip() or f"{name}的成长小故事",
        child_name=name,
        event=event,
        feeling=(data.get("feeling") or "").strip(),
        detail=(data.get("detail") or "").strip(),
        character=(data.get("character") or "").strip() or story.extract_character(event, name=name),
        model=model,
        pages=[
            {"text": (p.get("text") or "").strip(), "scene": (p.get("scene") or "").strip()}
            for p in pages
        ],
    )
    for pid in data.get("photo_ids") or []:
        if db.get_upload(pid):
            db.attach_upload(pid, book_id)
    return jsonify({"ok": True, "book": _book_json(db.get_book(book_id))})


@api.get("/books")
def list_books():
    out = []
    for b in db.list_books():
        out.append({
            "id": b["id"],
            "title": b["title"],
            "child_name": b["child_name"],
            "status": b["status"],
            "created_at": b["created_at"],
            "n_pages": b["n_pages"],
            "cover_url": f"/api/media/{b['id']}/{b['cover']}" if b.get("cover") else "",
        })
    return jsonify({"ok": True, "books": out})


@api.get("/books/<book_id>")
def get_book(book_id: str):
    book = db.get_book(book_id)
    if not book:
        return _err("小书不存在或已删除", 404)
    data = _book_json(book)
    data["generating"] = worker.busy(book_id)
    data["calls"] = db.book_calls(book_id)
    return jsonify({"ok": True, "book": data})


@api.patch("/books/<book_id>")
def patch_book(book_id: str):
    book = db.get_book(book_id)
    if not book:
        return _err("小书不存在", 404)
    data = request.get_json(silent=True) or {}

    fields = {}
    for key in ("title", "subtitle", "child_name", "character"):
        if key in data:
            fields[key] = (data[key] or "").strip()
    if fields:
        db.update_book(book_id, **fields)

    for p in data.get("pages") or []:
        try:
            idx = int(p.get("idx"))
        except (TypeError, ValueError):
            continue
        if not 1 <= idx <= config.PAGE_COUNT:
            continue
        upd = {}
        if "text" in p:
            upd["text"] = (p["text"] or "").strip()
        if "scene" in p:
            upd["scene"] = (p["scene"] or "").strip()
        if upd:
            db.update_page(book_id, idx, **upd)

    return jsonify({"ok": True, "book": _book_json(db.get_book(book_id))})


@api.delete("/books/<book_id>")
def delete_book(book_id: str):
    book = db.get_book(book_id)
    if not book:
        return _err("小书不存在", 404)
    db.soft_delete_book(book_id)
    for up in book.get("photos") or []:
        try:
            (config.UPLOAD_DIR / up["file"]).unlink(missing_ok=True)
        except Exception:
            pass
    book_dir = config.BOOKS_DIR / book_id
    if book_dir.exists():
        for f in book_dir.iterdir():
            f.unlink(missing_ok=True)
        book_dir.rmdir()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# 生成与重画
# ---------------------------------------------------------------------------
@api.post("/books/<book_id>/generate")
def generate(book_id: str):
    book = db.get_book(book_id)
    if not book:
        return _err("小书不存在", 404)
    if not book.get("photos"):
        return _err("请先上传至少一张宝宝照片")
    res = worker.start_book(book_id)
    if not res.get("started"):
        return _err(res.get("reason") or "已经在生成中")
    db.update_book(book_id, status="generating", error="")
    return jsonify({"ok": True})


@api.patch("/books/<book_id>/pages/<int:idx>")
def patch_page(book_id: str, idx: int):
    if not db.get_page(book_id, idx):
        return _err("这一页不存在", 404)
    data = request.get_json(silent=True) or {}
    upd = {}
    if "text" in data:
        upd["text"] = (data["text"] or "").strip()
    if "scene" in data:
        upd["scene"] = (data["scene"] or "").strip()
    if not upd:
        return _err("没有要修改的内容")
    db.update_page(book_id, idx, **upd)
    return jsonify({"ok": True, "page": {"idx": idx, **upd}})


@api.post("/books/<book_id>/pages/<int:idx>/regenerate")
def regenerate(book_id: str, idx: int):
    if not 1 <= idx <= config.PAGE_COUNT:
        return _err("页码超出范围")
    book = db.get_book(book_id)
    if not book:
        return _err("小书不存在", 404)
    if worker.busy(book_id):
        return _err("整本还在生成中，请稍等再重画")
    data = request.get_json(silent=True) or {}
    feedback = (data.get("feedback") or "").strip() or None
    if feedback and feedback not in FEEDBACKS:
        feedback = None
    res = worker.regenerate_page(book_id, idx, feedback)
    if not res["ok"]:
        return jsonify({"ok": False, "error": res["error"]}), 502
    return jsonify({"ok": True, "book": _book_json(db.get_book(book_id))})


# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------
@api.get("/books/<book_id>/export")
def export(book_id: str):
    book = db.get_book(book_id)
    if not book:
        return _err("小书不存在", 404)
    if any(not p["image"] for p in book["pages"]):
        return _err("还有页面没生成好，暂时无法导出")
    work_dir = config.BOOKS_DIR / book_id
    safe_title = (book["title"] or "小书").strip("《》").replace("/", "_").replace("\\", "_")
    zip_path = config.TMP_DIR / f"{safe_title}_{book_id}.zip"
    try:
        compose.export_zip(book, work_dir, work_dir, zip_path)
    except Exception as exc:  # noqa: BLE001
        return _err(f"导出失败：{exc}", 500)
    return send_file(zip_path, as_attachment=True, download_name=zip_path.name)


# ---------------------------------------------------------------------------
# 本地图片服务（只读本地目录，防目录穿越）
# ---------------------------------------------------------------------------
@api.get("/media/<book_id>/<path:name>")
def media_book(book_id: str, name: str):
    folder = config.BOOKS_DIR / pathlib.Path(book_id).name
    if not folder.is_dir():
        return _err("文件不存在", 404)
    return send_from_directory(folder, pathlib.Path(name).name, max_age=0)


@api.get("/media/up/<path:name>")
def media_upload(name: str):
    return send_from_directory(config.UPLOAD_DIR, pathlib.Path(name).name, max_age=0)
