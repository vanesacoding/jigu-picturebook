"""全局配置：路径、模型、预算、密钥读取。

安全约定（与 Seedream 实验报告一致）：
- API Key 只从环境变量 ARK_API_KEY 读取，或从 data/.env 读取（该文件被 .gitignore 排除）。
- Key 不写前端、不进日志、不落库，日志里只出现掩码。
"""

from __future__ import annotations

import os
import pathlib

APP_ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = pathlib.Path(os.environ.get("JIGU_DATA_DIR") or (APP_ROOT / "data"))
WEB_DIR = APP_ROOT / "web"
BOOKS_DIR = DATA_DIR / "books"
UPLOAD_DIR = DATA_DIR / "uploads"
TMP_DIR = DATA_DIR / "tmp"
DB_PATH = DATA_DIR / "books.db"
CALL_LOG = DATA_DIR / "calls.jsonl"

# ---------------------------------------------------------------------------
# 模型：以实验报告推荐方案为准，但启动时会真实核验可用性，不假设 ID 恒定
# ---------------------------------------------------------------------------
DEFAULT_MODEL = os.environ.get("JIGU_MODEL", "doubao-seedream-5-0-flash-260915")
MODEL_CANDIDATES = [
    os.environ.get("JIGU_MODEL", "").strip(),
    "doubao-seedream-5-0-flash-260915",
    "doubao-seedream-5-0-pro-260628",
    "doubao-seedream-4-0-20260415",
    "doubao-seedream-4-5-251128",
    "doubao-seedream-5-0-lite-260128",
]
MODEL_CANDIDATES = [m for m in dict.fromkeys(MODEL_CANDIDATES) if m]

# 5.0 flash / pro 的 3:4 2K 像素尺寸；4.0 / 5.0 lite / 4.5 为 1728x2304
SIZE_3X4_HIRES = "1776x2368"
SIZE_3X4 = "1728x2304"
MODEL_SIZE_HINT = {
    "doubao-seedream-5-0-flash": SIZE_3X4_HIRES,
    "doubao-seedream-5-0-pro": SIZE_3X4_HIRES,
    "doubao-seedream-5-0-lite": SIZE_3X4,
    "doubao-seedream-4-5": SIZE_3X4,
    "doubao-seedream-4-0": SIZE_3X4,
}

PRICE_CNY_PER_IMAGE = {
    "doubao-seedream-5-0-lite": 0.22,
    "doubao-seedream-4-5": 0.25,
    "doubao-seedream-4-0": 0.20,
    "doubao-seedream-5-0-flash": 0.12,
    "doubao-seedream-5-0-pro": 0.30,
}

PAGE_COUNT = 5
MAX_PHOTOS = 6
PROMPT_CHAR_LIMIT = 300

# V0 私有自用：整站累计花费保护，避免误触发批量生成烧钱
APP_BUDGET_CNY = float(os.environ.get("JIGU_BUDGET_CNY", "10"))

HOST = os.environ.get("JIGU_HOST", "127.0.0.1")
PORT = int(os.environ.get("JIGU_PORT", "7860"))

# 楷体：排版用。找不到时退回微软雅黑
FONT_CANDIDATES = [
    pathlib.Path(r"C:\Windows\Fonts\simkai.ttf"),
    pathlib.Path(r"C:\Windows\Fonts\msyh.ttc"),
    pathlib.Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
]


def ensure_dirs() -> None:
    for d in (DATA_DIR, BOOKS_DIR, UPLOAD_DIR, TMP_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _load_dotenv() -> None:
    """从 data/.env 读取本地配置（Key 不进代码仓库）。"""
    env_file = DATA_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def get_api_key() -> str:
    _load_dotenv()
    key = os.environ.get("ARK_API_KEY", "").strip()
    if not key:
        raise RuntimeError("未配置 ARK_API_KEY，请在环境变量或 data/.env 中设置后重启。")
    return key


def mask(key: str) -> str:
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-2:]}(len={len(key)})"


def price_for(model_id: str) -> float:
    for prefix, price in PRICE_CNY_PER_IMAGE.items():
        if model_id.startswith(prefix):
            return price
    return 0.0


def size_for(model_id: str) -> str:
    for prefix, size in MODEL_SIZE_HINT.items():
        if model_id.startswith(prefix):
            return size
    return SIZE_3X4


def font_path() -> pathlib.Path | None:
    for p in FONT_CANDIDATES:
        if p.exists():
            return p
    return None
