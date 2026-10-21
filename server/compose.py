"""服务端排版与导出：把插画 + 文字排成 3:4 书页，并打包成 ZIP / PDF。

版式（与 Seedream 实验成书一致）：
- 1500×2000（3:4），奶油白纸面
- 插画约占 75%，文字在下方独立排版，图内无文字
- 封面书名由程序排版；页码小而克制
- 文字自动按宽度折行，行数过多时自动缩字号，避免溢出版心
"""

from __future__ import annotations

import io
import json
import pathlib
import zipfile

from PIL import Image, ImageDraw, ImageFont

from . import config

PAGE_W, PAGE_H = 1500, 2000
CREAM = (250, 246, 239)
INK = (74, 66, 60)
SUBTLE = (150, 140, 128)
BORDER = (226, 216, 202)
MARGIN_X = 110
TEXT_WIDTH = PAGE_W - 2 * MARGIN_X


def load_font(size: int, serif: bool = True) -> ImageFont.FreeTypeFont:
    font = config.font_path()
    if font:
        try:
            return ImageFont.truetype(str(font), size)
        except Exception:
            pass
    return ImageFont.load_default()


def cover_fit(img: Image.Image, box_w: int, box_h: int) -> Image.Image:
    img = img.convert("RGB")
    sw, sh = img.size
    scale = max(box_w / sw, box_h / sh)
    nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - box_w) // 2
    top = (nh - box_h) // 2
    return img.crop((left, top, left + box_w, top + box_h))


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_w: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """按像素宽度折行；中文逐字折，英文/数字按词。"""
    lines: list[str] = []
    for para in (text or "").split("\n"):
        if not para:
            continue
        cur = ""
        for ch in para:
            trial = cur + ch
            if draw.textlength(trial, font=font) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
    return lines


def _draw_centered(draw: ImageDraw.ImageDraw, y: int, text: str, font, fill) -> int:
    if not text:
        return y
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    draw.text(((PAGE_W - w) // 2, y - bbox[1]), text, font=font, fill=fill)
    return y + (bbox[3] - bbox[1])


def compose_cover(image_path: pathlib.Path, title: str, subtitle: str, out: pathlib.Path) -> None:
    page = Image.new("RGB", (PAGE_W, PAGE_H), CREAM)
    draw = ImageDraw.Draw(page)

    y = 120
    y = _draw_centered(draw, y, title, load_font(96, True), INK) + 34
    y = _draw_centered(draw, y, subtitle, load_font(46, True), SUBTLE) + 60

    box_w = 1180
    box_h = 1560
    top = y
    if top + box_h > PAGE_H - 40:
        box_h = max(200, PAGE_H - 40 - top)
    page.paste(cover_fit(Image.open(image_path), box_w, box_h), ((PAGE_W - box_w) // 2, top))
    draw.rectangle(
        [((PAGE_W - box_w) // 2, top), ((PAGE_W + box_w) // 2, top + box_h)],
        outline=BORDER,
        width=2,
    )
    page.save(out, quality=95)


def compose_page(image_path: pathlib.Path, text: str, page_no: int, out: pathlib.Path) -> None:
    page = Image.new("RGB", (PAGE_W, PAGE_H), CREAM)
    draw = ImageDraw.Draw(page)

    box_w = TEXT_WIDTH
    box_h = round(box_w * 4 / 3)
    top = 90
    page.paste(cover_fit(Image.open(image_path), box_w, box_h), (MARGIN_X, top))
    draw.rectangle([(MARGIN_X, top), (MARGIN_X + box_w, top + box_h)], outline=BORDER, width=2)

    text_y = top + box_h + 56
    avail = PAGE_H - 90 - text_y - 60
    chosen: tuple[int, list[str]] | None = None
    for size in (46, 42, 38, 34, 30):
        font = load_font(size, True)
        lines = wrap_text(text, font, TEXT_WIDTH, draw)
        line_h = round(size * 1.62)
        if len(lines) * line_h <= avail:
            chosen = (size, lines)
            break
    if chosen is None:
        font = load_font(30, True)
        lines = wrap_text(text, font, TEXT_WIDTH, draw)
        chosen = (30, lines)

    size, lines = chosen
    font = load_font(size, True)
    line_h = round(size * 1.62)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        draw.text(((PAGE_W - (bbox[2] - bbox[0])) // 2, text_y - bbox[1]), line, font=font, fill=INK)
        text_y += line_h

    num_font = load_font(30, False)
    num = str(page_no)
    bbox = draw.textbbox((0, 0), num, font=num_font)
    draw.text(
        (PAGE_W - MARGIN_X - (bbox[2] - bbox[0]), PAGE_H - 78 - bbox[3]),
        num,
        font=num_font,
        fill=SUBTLE,
    )
    page.save(out, quality=95)


def compose_book(book: dict, image_dir: pathlib.Path, out_dir: pathlib.Path) -> list[pathlib.Path]:
    """把整本小书排版成 5 张图，返回文件路径。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = sorted(book.get("pages") or [], key=lambda p: p["idx"])
    if len(pages) < config.PAGE_COUNT:
        raise ValueError("页数不足，无法排版。")
    outs: list[pathlib.Path] = []
    for p in pages:
        img = image_dir / (p.get("image") or "")
        if not img.exists():
            raise ValueError(f"第 {p['idx']} 页插画缺失，无法排版。")
        if p["idx"] == 1:
            target = out_dir / "1_封面.jpg"
            compose_cover(img, book.get("title") or "", book.get("subtitle") or "", target)
        else:
            target = out_dir / f"{p['idx']}_第{p['idx'] - 1}页.jpg"
            compose_page(img, p.get("text") or "", p["idx"] - 1, target)
        outs.append(target)
    return outs


# ---------------------------------------------------------------------------
# 极简 PDF（仅嵌入 JPEG，无需第三方依赖）
# ---------------------------------------------------------------------------
def build_pdf(jpegs: list[pathlib.Path], out_pdf: pathlib.Path, dpi: int = 150) -> pathlib.Path:
    w_pt = round(PAGE_W / dpi * 72, 2)
    h_pt = round(PAGE_H / dpi * 72, 2)

    objs: list[bytes] = []

    def add(obj: bytes) -> int:
        objs.append(obj)
        return len(objs)

    # 先占位：1 = Catalog, 2 = Pages
    objs.append(b"")
    objs.append(b"")
    kids = []
    for jpg in jpegs:
        raw = jpg.read_bytes()
        with Image.open(io.BytesIO(raw)) as im:
            iw, ih = im.size
        img_no = add(
            f"<< /Type /XObject /Subtype /Image /Width {iw} /Height {ih} "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
            f"/Length {len(raw)} >>\nstream\n".encode("ascii") + raw + b"\nendstream"
        )
        content = f"q {w_pt} 0 0 {h_pt} 0 0 cm /Im0 Do Q".encode("ascii")
        cont_no = add(
            f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream"
        )
        page_no = add(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w_pt} {h_pt}] "
            f"/Resources << /XObject << /Im0 {img_no} 0 R >> >> /Contents {cont_no} 0 R >>".encode("ascii")
        )
        kids.append(page_no)

    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode("ascii")
    )

    buf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(buf))
        buf += f"{i} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"

    xref_at = len(buf)
    buf += f"xref\n0 {len(objs) + 1}\n".encode("ascii")
    buf += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        buf += f"{off:010d} 00000 n \n".encode("ascii")
    buf += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode("ascii")
    )
    out_pdf.write_bytes(bytes(buf))
    return out_pdf


def export_zip(book: dict, image_dir: pathlib.Path, work_dir: pathlib.Path, zip_path: pathlib.Path) -> pathlib.Path:
    """导出整本：排版图 + PDF + 文字稿，打包为 ZIP。"""
    composed_dir = work_dir / "composed"
    if composed_dir.exists():
        for f in composed_dir.iterdir():
            f.unlink()
    pages = compose_book(book, image_dir, composed_dir)
    pdf = build_pdf(pages, work_dir / f"{book.get('title', '小书').strip('《》')}.pdf")

    readme = [
        f"书名：{book.get('title', '')}",
        f"副标题：{book.get('subtitle', '')}",
        f"宝宝：{book.get('child_name', '')}",
        "",
        "—— 五页文字 ——",
    ]
    for p in sorted(book.get("pages") or [], key=lambda x: x["idx"]):
        label = "封面" if p["idx"] == 1 else f"第 {p['idx'] - 1} 页"
        readme.append(f"{label}：{p.get('text', '')}")
    readme += ["", "由「叽咕插画 V0」生成 · 仅私人使用"]

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in pages:
            zf.write(p, arcname=p.name)
        zf.write(pdf, arcname=pdf.name)
        zf.writestr("故事文字.txt", "\n".join(readme))
        zf.writestr(
            "book.json",
            json.dumps(
                {k: book.get(k) for k in ("id", "title", "subtitle", "child_name", "model", "created_at")},
                ensure_ascii=False,
                indent=2,
            ),
        )
    return zip_path
