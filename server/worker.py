"""后台生成线程：逐页生成插画、单页重画、失败兜底。

设计取舍：
- 逐页生成（不用组图），因为 5.0 flash 不支持组图参数，且实验证明逐页的镜头变化更好。
- 每页独立失败、独立重画，一页坏不影响另外四页。
- 每页都记录真实 usage 与费用，整本成本可对账。
"""

from __future__ import annotations

import pathlib
import threading
import time

from . import ark, config, db, prompt

_MODEL_CACHE: dict[str, object] = {"model": None, "probe": None, "at": 0.0}
_MODEL_TTL = 1800
_JOBS: dict[str, threading.Thread] = {}
_JOBS_LOCK = threading.Lock()


def current_model(force: bool = False) -> tuple[str, dict]:
    """带缓存地确认可用模型；模型 ID 会变，所以每次启动都真实核验。"""
    now = time.time()
    if not force and _MODEL_CACHE["model"] and now - float(_MODEL_CACHE["at"]) < _MODEL_TTL:
        return _MODEL_CACHE["model"], _MODEL_CACHE["probe"]  # type: ignore[return-value]
    model, probe = ark.resolve_model(config.DEFAULT_MODEL)
    _MODEL_CACHE.update({"model": model, "probe": probe, "at": now})
    return model, probe


def model_status() -> dict:
    try:
        model, probe = current_model()
        return {"ok": True, "model": model, "probe": probe}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "probe": {}}


def _budget_ok() -> tuple[bool, str]:
    spent = db.spent_total()
    if spent >= config.APP_BUDGET_CNY:
        return False, f"已达到本应用的花费上限（¥{config.APP_BUDGET_CNY:.0f}，已用 ¥{spent:.2f}）。"
    return True, ""


def _photo_paths(book_id: str, limit: int = 2) -> list[pathlib.Path]:
    paths = []
    for up in db.list_uploads(book_id):
        p = config.UPLOAD_DIR / up["file"]
        if p.exists():
            paths.append(p)
    return paths[:limit]


def _render_page(book_id: str, idx: int, feedback: str | None = None) -> dict:
    """生成或重画一页，返回 {ok, error, cost}。"""
    book = db.get_book(book_id)
    if not book:
        return {"ok": False, "error": "小书不存在", "cost": 0.0}

    ok, why = _budget_ok()
    if not ok:
        db.update_page(book_id, idx, status="failed", error=why)
        return {"ok": False, "error": why, "cost": 0.0}

    model = book.get("model") or config.DEFAULT_MODEL
    text = prompt.build_page_prompt(book, idx, feedback)
    refs = _photo_paths(book_id)

    db.update_page(book_id, idx, status="running", error="")
    res = ark.generate_image(model=model, prompt=text, ref_images=refs)

    cost = float(res.cost_cny or 0.0)
    db.log_call(
        book_id=book_id,
        page_idx=idx,
        record_id=res.record_id,
        model=model,
        prompt=text,
        http_status=res.http_status,
        ok=res.ok,
        n_images=1 if res.file else 0,
        cost_cny=cost,
        elapsed_s=res.elapsed_s,
        error=res.error,
    )

    if not res.ok or res.file is None:
        err = res.error or "生成失败，请重画本页。"
        db.update_page(book_id, idx, status="failed", error=err, prompt=text, cost_cny=cost)
        return {"ok": False, "error": err, "cost": cost}

    book_dir = config.BOOKS_DIR / book_id
    book_dir.mkdir(parents=True, exist_ok=True)
    page = db.get_page(book_id, idx) or {}
    versions = page.get("versions") or []
    n = len(versions) + 1
    fname = f"p{idx}.jpg" if n == 1 else f"p{idx}_v{n}.jpg"
    target = book_dir / fname
    try:
        target.write_bytes(res.file.read_bytes())
        res.file.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        err = f"保存插画失败：{exc}"
        db.update_page(book_id, idx, status="failed", error=err)
        return {"ok": False, "error": err, "cost": cost}

    versions.append({"file": fname, "ts": db.now(), "feedback": feedback or "", "record_id": res.record_id})
    db.update_page(
        book_id,
        idx,
        image=fname,
        versions=versions,
        status="done",
        error="",
        prompt=text,
        cost_cny=cost,
        redraws=(page.get("redraws") or 0) + (1 if feedback else 0),
    )
    return {"ok": True, "error": "", "cost": cost}


def _finish(book_id: str) -> None:
    pages = db.all_pages(book_id)
    done = sum(1 for p in pages if p["image"])
    status = "ready" if done == len(pages) else ("partial" if done else "failed")
    db.update_book(book_id, status=status)


def _sync_cost(book_id: str) -> None:
    """整本花费以真实调用记录为准（重画会覆盖页面 cost，不能再拿页面 cost 相加）。"""
    total = sum(float(c.get("cost_cny") or 0) for c in db.book_calls(book_id))
    db.update_book(book_id, cost_cny=round(total, 4))


def _run_book(book_id: str) -> None:
    try:
        pages = db.all_pages(book_id)
        for p in pages:
            if p["image"]:
                continue
            _render_page(book_id, p["idx"])
    except ark.ArkError as exc:
        db.update_book(book_id, status="failed", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        db.update_book(book_id, status="failed", error=f"生成中断：{type(exc).__name__}: {exc}")
    finally:
        _sync_cost(book_id)
        _finish(book_id)
        with _JOBS_LOCK:
            _JOBS.pop(book_id, None)


def start_book(book_id: str) -> dict:
    """启动整本生成（后台线程），立即返回。"""
    with _JOBS_LOCK:
        if book_id in _JOBS:
            return {"started": False, "reason": "已在生成中"}
        t = threading.Thread(target=_run_book, args=(book_id,), daemon=True, name=f"gen-{book_id}")
        _JOBS[book_id] = t
        t.start()
    return {"started": True}


def regenerate_page(book_id: str, idx: int, feedback: str | None = None) -> dict:
    """同步重画单页（家长等着看，不必再开线程）。"""
    r = _render_page(book_id, idx, feedback)
    _sync_cost(book_id)
    _finish(book_id)
    return r


def busy(book_id: str) -> bool:
    with _JOBS_LOCK:
        return book_id in _JOBS
