"""SQLite 存储层：小书、页、上传照片、调用审计。

V0 是私有单用户应用，用 SQLite + 本地文件足够，不做多租户与用户体系。
所有写操作串行化（生成线程与请求线程并发写）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid

from . import config

_LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL DEFAULT '',
    subtitle     TEXT NOT NULL DEFAULT '',
    child_name   TEXT NOT NULL DEFAULT '',
    style        TEXT NOT NULL DEFAULT 'B_color',
    status       TEXT NOT NULL DEFAULT 'drafting',
    event        TEXT NOT NULL DEFAULT '',
    feeling      TEXT NOT NULL DEFAULT '',
    detail       TEXT NOT NULL DEFAULT '',
    character    TEXT NOT NULL DEFAULT '',
    model        TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT 'v2',
    cost_cny     REAL NOT NULL DEFAULT 0,
    error        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    deleted_at   TEXT
);

CREATE TABLE IF NOT EXISTS pages (
    book_id   TEXT NOT NULL,
    idx       INTEGER NOT NULL,
    text      TEXT NOT NULL DEFAULT '',
    scene     TEXT NOT NULL DEFAULT '',
    image     TEXT NOT NULL DEFAULT '',
    versions  TEXT NOT NULL DEFAULT '[]',
    status    TEXT NOT NULL DEFAULT 'pending',
    error     TEXT NOT NULL DEFAULT '',
    prompt    TEXT NOT NULL DEFAULT '',
    cost_cny  REAL NOT NULL DEFAULT 0,
    redraws   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (book_id, idx)
);

CREATE TABLE IF NOT EXISTS uploads (
    id         TEXT PRIMARY KEY,
    book_id    TEXT NOT NULL,
    file       TEXT NOT NULL,
    orig_name  TEXT NOT NULL DEFAULT '',
    width      INTEGER NOT NULL DEFAULT 0,
    height     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id     TEXT NOT NULL DEFAULT '',
    page_idx    INTEGER NOT NULL DEFAULT 0,
    record_id   TEXT NOT NULL DEFAULT '',
    model       TEXT NOT NULL DEFAULT '',
    prompt      TEXT NOT NULL DEFAULT '',
    http_status INTEGER NOT NULL DEFAULT 0,
    ok          INTEGER NOT NULL DEFAULT 0,
    n_images    INTEGER NOT NULL DEFAULT 0,
    cost_cny    REAL NOT NULL DEFAULT 0,
    elapsed_s   REAL NOT NULL DEFAULT 0,
    error       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_books_created ON books(deleted_at, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_uploads_book ON uploads(book_id);
"""


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    config.ensure_dirs()
    with _LOCK, connect() as conn:
        conn.executescript(SCHEMA)


def _row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r else None


# ---------------------------------------------------------------------------
# 小书
# ---------------------------------------------------------------------------
def create_book(
    *,
    title: str,
    subtitle: str,
    child_name: str,
    event: str,
    feeling: str,
    detail: str,
    character: str,
    model: str,
    pages: list[dict],
) -> str:
    book_id = new_id("bk")
    ts = now()
    with _LOCK, connect() as conn:
        conn.execute(
            "INSERT INTO books (id,title,subtitle,child_name,style,status,event,feeling,detail,"
            "character,model,cost_cny,created_at,updated_at) "
            "VALUES (?,?,?,?,'B_color','review',?,?,?,?,?,0,?,?)",
            (book_id, title, subtitle, child_name, event, feeling, detail, character, model, ts, ts),
        )
        for i, p in enumerate(pages, start=1):
            conn.execute(
                "INSERT INTO pages (book_id,idx,text,scene,status) VALUES (?,?,?,?,'pending')",
                (book_id, i, p.get("text", ""), p.get("scene", "")),
            )
    return book_id


def get_book(book_id: str, with_pages: bool = True) -> dict | None:
    with _LOCK, connect() as conn:
        row = conn.execute(
            "SELECT * FROM books WHERE id=? AND deleted_at IS NULL", (book_id,)
        ).fetchone()
        if not row:
            return None
        book = dict(row)
        if with_pages:
            pages = conn.execute(
                "SELECT * FROM pages WHERE book_id=? ORDER BY idx", (book_id,)
            ).fetchall()
            book["pages"] = [dict(p) for p in pages]
            for p in book["pages"]:
                try:
                    p["versions"] = json.loads(p["versions"] or "[]")
                except Exception:
                    p["versions"] = []
    book["photos"] = list_uploads(book_id)
    return book


def list_books() -> list[dict]:
    with _LOCK, connect() as conn:
        rows = conn.execute(
            "SELECT b.*, (SELECT image FROM pages p WHERE p.book_id=b.id AND p.idx=1) AS cover, "
            "(SELECT COUNT(*) FROM pages p WHERE p.book_id=b.id AND p.image<>'') AS n_pages "
            "FROM books b WHERE b.deleted_at IS NULL ORDER BY b.created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_book(book_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = now()
    sets = ", ".join(f"{k}=?" for k in fields)
    with _LOCK, connect() as conn:
        conn.execute(f"UPDATE books SET {sets} WHERE id=?", (*fields.values(), book_id))


def soft_delete_book(book_id: str) -> None:
    with _LOCK, connect() as conn:
        conn.execute(
            "UPDATE books SET deleted_at=?, updated_at=? WHERE id=?", (now(), now(), book_id)
        )


# ---------------------------------------------------------------------------
# 页
# ---------------------------------------------------------------------------
def get_page(book_id: str, idx: int) -> dict | None:
    with _LOCK, connect() as conn:
        row = conn.execute(
            "SELECT * FROM pages WHERE book_id=? AND idx=?", (book_id, idx)
        ).fetchone()
    p = _row(row)
    if p:
        try:
            p["versions"] = json.loads(p["versions"] or "[]")
        except Exception:
            p["versions"] = []
    return p


def update_page(book_id: str, idx: int, **fields) -> None:
    if not fields:
        return
    if "versions" in fields and not isinstance(fields["versions"], str):
        fields["versions"] = json.dumps(fields["versions"], ensure_ascii=False)
    sets = ", ".join(f"{k}=?" for k in fields)
    with _LOCK, connect() as conn:
        conn.execute(
            f"UPDATE pages SET {sets} WHERE book_id=? AND idx=?", (*fields.values(), book_id, idx)
        )


def all_pages(book_id: str) -> list[dict]:
    with _LOCK, connect() as conn:
        rows = conn.execute(
            "SELECT * FROM pages WHERE book_id=? ORDER BY idx", (book_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 上传照片
# ---------------------------------------------------------------------------
def add_upload(book_id: str, file: str, orig_name: str, width: int, height: int) -> str:
    up_id = new_id("ph")
    with _LOCK, connect() as conn:
        conn.execute(
            "INSERT INTO uploads (id,book_id,file,orig_name,width,height,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (up_id, book_id, file, orig_name, width, height, now()),
        )
    return up_id


def list_uploads(book_id: str) -> list[dict]:
    with _LOCK, connect() as conn:
        rows = conn.execute(
            "SELECT * FROM uploads WHERE book_id=? ORDER BY created_at", (book_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def attach_upload(up_id: str, book_id: str) -> None:
    with _LOCK, connect() as conn:
        conn.execute("UPDATE uploads SET book_id=? WHERE id=?", (book_id, up_id))


def get_upload(up_id: str) -> dict | None:
    with _LOCK, connect() as conn:
        row = conn.execute("SELECT * FROM uploads WHERE id=?", (up_id,)).fetchone()
    return _row(row)


def delete_upload(up_id: str) -> dict | None:
    up = get_upload(up_id)
    if not up:
        return None
    with _LOCK, connect() as conn:
        conn.execute("DELETE FROM uploads WHERE id=?", (up_id,))
    return up


# ---------------------------------------------------------------------------
# 调用审计与花费
# ---------------------------------------------------------------------------
def log_call(
    *,
    book_id: str,
    page_idx: int,
    record_id: str,
    model: str,
    prompt: str,
    http_status: int,
    ok: bool,
    n_images: int,
    cost_cny: float,
    elapsed_s: float,
    error: str,
) -> None:
    with _LOCK, connect() as conn:
        conn.execute(
            "INSERT INTO calls (book_id,page_idx,record_id,model,prompt,http_status,ok,n_images,"
            "cost_cny,elapsed_s,error,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                book_id, page_idx, record_id, model, prompt, http_status, 1 if ok else 0,
                n_images, cost_cny, elapsed_s, error[:800], now(),
            ),
        )


def spent_total() -> float:
    with _LOCK, connect() as conn:
        row = conn.execute("SELECT COALESCE(SUM(cost_cny),0) AS s FROM calls").fetchone()
    return round(float(row["s"] or 0), 4)


def book_calls(book_id: str) -> list[dict]:
    with _LOCK, connect() as conn:
        rows = conn.execute(
            "SELECT * FROM calls WHERE book_id=? ORDER BY id", (book_id,)
        ).fetchall()
    return [dict(r) for r in rows]
