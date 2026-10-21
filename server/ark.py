"""火山方舟 Seedream 图片生成客户端（复用 Seedream 实验已验证的参数与坑位）。

实测结论（2026-10-21，详见 jigu-seedream/report/研究报告.md）：
1. `sequential_image_generation` 对 5.0 flash / pro 不支持，连 "disabled" 都报
   InvalidParameter，必须整个字段不出现 —— 本模块只用逐页生成，故从不传该字段。
2. `size: "2K"` 不等于 3:4，必须写死像素尺寸（flash 用 1776x2368，4.0 用 1728x2304）。
3. `watermark` 默认 true，必须显式传 false。
4. 计费按 `usage.generated_images`，输入参考图不计费。
"""

from __future__ import annotations

import base64
import io
import json
import pathlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import requests

from . import config

BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
GENERATIONS_PATH = "/images/generations"
MODELS_PATH = "/models"


class ArkError(RuntimeError):
    """模型侧可读错误，前端可直接展示。"""


@dataclass
class GenerateResult:
    ok: bool
    record_id: str
    file: pathlib.Path | None = None
    size: str = ""
    http_status: int = 0
    elapsed_s: float = 0.0
    cost_cny: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    params: dict[str, Any] = field(default_factory=dict)


def image_to_data_url(path: pathlib.Path, max_side: int = 2048) -> str:
    """本地照片 → base64 data URL。不上传任何公共图床。"""
    from PIL import Image

    img = Image.open(path)
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def generate_image(
    *,
    model: str,
    prompt: str,
    ref_images: list[pathlib.Path] | None = None,
    size: str | None = None,
    timeout: int = 300,
    max_retries: int = 1,
) -> GenerateResult:
    """调用一次 Seedream 单图生成，落盘并返回结果。"""
    api_key = config.get_api_key()
    ref_images = ref_images or []
    size = size or config.size_for(model)

    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "response_format": "url",
        "watermark": False,
    }
    if ref_images:
        urls = [image_to_data_url(p) for p in ref_images]
        payload["image"] = urls[0] if len(urls) == 1 else urls

    record_id = uuid.uuid4().hex[:12]
    safe_params = {k: v for k, v in payload.items() if k != "image"}
    safe_params["n_ref_images"] = len(ref_images)

    attempt = 0
    while True:
        attempt += 1
        t0 = time.time()
        try:
            resp = requests.post(
                BASE_URL + GENERATIONS_PATH,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            elapsed = round(time.time() - t0, 2)
            if attempt <= max_retries:
                time.sleep(3 * attempt)
                continue
            return GenerateResult(
                ok=False, record_id=record_id, elapsed_s=elapsed, params=safe_params,
                error=f"网络异常：{type(exc).__name__}。请检查网络后重画本页。",
            )

        elapsed = round(time.time() - t0, 2)
        body: dict[str, Any] = {}
        try:
            body = resp.json() if resp.content else {}
        except Exception:
            body = {}

        if resp.status_code != 200:
            code = ""
            err_obj = body.get("error") or {}
            if isinstance(err_obj, dict):
                code = err_obj.get("code") or ""
            msg = _friendly_error(resp.status_code, code, body)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt <= max_retries:
                time.sleep(5 * attempt)
                continue
            return GenerateResult(
                ok=False, record_id=record_id, http_status=resp.status_code,
                elapsed_s=elapsed, params=safe_params, error=msg,
            )

        data = body.get("data") or []
        usage = body.get("usage") or {}
        if not data:
            return GenerateResult(
                ok=False, record_id=record_id, http_status=200, elapsed_s=elapsed,
                params=safe_params, usage=usage,
                error="模型未返回图片，请重画本页。",
            )

        item = data[0]
        if item.get("error"):
            return GenerateResult(
                ok=False, record_id=record_id, http_status=200, elapsed_s=elapsed,
                params=safe_params, usage=usage,
                error="模型返回错误：" + json.dumps(item["error"], ensure_ascii=False)[:200],
            )

        url = item.get("url")
        if not url:
            return GenerateResult(
                ok=False, record_id=record_id, http_status=200, elapsed_s=elapsed,
                params=safe_params, usage=usage, error="模型未返回可下载地址，请重画本页。",
            )

        return GenerateResult(
            ok=True,
            record_id=record_id,
            size=item.get("size", ""),
            http_status=200,
            elapsed_s=elapsed,
            cost_cny=round(int(usage.get("generated_images") or 1) * config.price_for(model), 4),
            usage=usage,
            params=safe_params,
            file=_download(url, record_id),
        )


def _download(url: str, record_id: str) -> pathlib.Path | None:
    """临时落到 data/tmp，由调用方移动到 book 目录。"""
    try:
        resp = requests.get(url, timeout=180)
        resp.raise_for_status()
        config.TMP_DIR.mkdir(parents=True, exist_ok=True)
        path = config.TMP_DIR / f"gen_{record_id}.jpg"
        path.write_bytes(resp.content)
        return path
    except Exception:
        return None


def _friendly_error(status: int, code: str, body: dict) -> str:
    """把接口错误翻译成家长能看懂的一句话。"""
    if code == "ModelNotOpen":
        return "该模型未在当前账号开通。请到火山方舟控制台开通后重试，或换用已开通的模型。"
    if code in ("InvalidEndpointOrModel.NotFound", "InvalidEndpointOrModel.NotFoundError"):
        return "当前配置的模型不存在或不可用，请在控制台确认 Model ID 后修改配置。"
    if code == "InvalidParameter":
        detail = ""
        err = body.get("error") or {}
        if isinstance(err, dict):
            detail = str(err.get("message") or "")
        return "请求参数不被该模型接受" + (f"：{detail[:120]}" if detail else "") + "。"
    if code in ("AuthenticationError", "Unauthorized"):
        return "API Key 无效或已失效，请重新配置服务端密钥。"
    if status == 429:
        return "调用太频繁，已被限流，请稍后重画本页。"
    if status >= 500:
        return "模型服务暂时不稳定，请稍后重画本页。"
    raw = json.dumps(body, ensure_ascii=False)[:200]
    return f"生成失败（HTTP {status}）{raw}"


def probe_models() -> dict[str, Any]:
    """零费用核验模型可用性：只传 model、不带 prompt。

    返回 {model_id: {"verdict": ..., "http": ..., "message": ...}}
    """
    api_key = config.get_api_key()
    out: dict[str, Any] = {}
    for model in config.MODEL_CANDIDATES:
        try:
            resp = requests.post(
                BASE_URL + GENERATIONS_PATH,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                data=json.dumps({"model": model}).encode("utf-8"),
                timeout=30,
            )
            body = {}
            try:
                body = resp.json()
            except Exception:
                pass
            code = ((body.get("error") or {}) if isinstance(body.get("error"), dict) else {}).get("code", "")
            if code == "ModelNotOpen":
                verdict = "not_open"
            elif code in ("InvalidEndpointOrModel.NotFound", "InvalidEndpointOrModel.NotFoundError"):
                verdict = "not_found"
            elif resp.status_code == 200:
                verdict = "ok"
            elif resp.status_code == 400:
                verdict = "ok"  # 参数校验已到，说明模型可用
            else:
                verdict = "unknown"
            out[model] = {
                "verdict": verdict,
                "http": resp.status_code,
                "code": code,
                "message": str(code or "")[:120],
            }
        except requests.RequestException as exc:
            out[model] = {"verdict": "network_error", "http": 0, "code": "", "message": str(exc)[:120]}
    return out


def resolve_model(preferred: str | None = None) -> tuple[str, dict[str, Any]]:
    """确定实际可用模型：优先用户配置，未开通时自动退到第一个可用模型。"""
    probe = probe_models()
    order = [m for m in ([preferred] if preferred else []) + config.MODEL_CANDIDATES if m]
    for model in dict.fromkeys(order):
        info = probe.get(model) or {}
        if info.get("verdict") == "ok":
            return model, probe
    raise ArkError(
        "没有可用的 Seedream 模型。请在火山方舟控制台开通后重试，"
        "或设置环境变量 JIGU_MODEL 指定已开通的 Model ID。"
    )
