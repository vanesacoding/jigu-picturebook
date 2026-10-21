"""四段式提示词构建（按 Seedream 实验报告 v2 结构，改为动态生成）。

Part 1 固定画风 —— 整本统一，V0 只有彩色小绘本
Part 2 固定人物 —— 称呼、脸、衣物配饰，每页一字不改
Part 3 本页场景 —— 家长确认过的画面描述 + 机位（强制镜头变化）
Part 4 负面约束 —— 故事里没有的一切都不许出现；图内不许有文字

实验验证过的两条硬规则写进本模块：
- 四段之间不允许互相矛盾（矛盾是幻觉第一诱因）。
- Part 3 必须落到具体身体动作，不能停在"她很开心"这类抽象状态。
"""

from __future__ import annotations

from . import config

STYLE_BLOCK = (
    "儿童绘本插画，水彩手绘，低饱和柔和配色（暖白、浅杏、雾蓝、草绿），"
    "暖白纸感背景，背景简化、留白充足，人物五官自然、略作卡通化。"
)

# 五页默认机位：整本要有远近变化，至少两页是全身/大半身，能看到房间与地面，
# 只有封面允许偏近，避免整本都是正面大头照。
FRAMING = {
    1: "封面，半身近景，头顶到胸口，身后环境虚化",
    2: "中景，人物与身边的环境一起入画，能看到旁边的家具",
    3: "全身，从头到脚完整在画面内，能看到脚下地面",
    4: "大半身，动作幅度大，能看到手臂动作",
    5: "中景，人物偏画面一侧，留白多",
}
FRAMING_ALT = {
    1: "封面，侧面半身，画面右上留白",
    2: "稍远的中景，环境多露一些",
    3: "中景，正侧面，能看到手部动作",
    4: "侧面大半身，人物偏画面左侧",
    5: "近景，胸口以上，表情放松",
}

NEGATIVE_BASE = (
    "不添加故事里没有的人物、道具、动物；不画王冠、权杖、宫殿、医生、药物、书本、玩具；"
    "不换脸型与服饰；图片内没有任何文字；背景简单、无强光；"
    "景别按本页要求，不要每页都画正面大头照；不要3D照片感、夸张大眼、畸形手指。"
)

FEEDBACK_PREFIX = {
    "unlike": "严格参照参考照片：脸型、五官、眉眼与照片里的孩子一致，眼睛不要放大，",
    "scene": "只画本页描述的场景与动作，不要添加其他家具、装饰与物件，",
    "variation": "换一个机位与景别重画，",
}
FEEDBACK_FRAMING = {
    "variation": FRAMING_ALT,
}


def character_block(book: dict) -> str:
    name = (book.get("child_name") or "宝宝").strip()
    look = (book.get("character") or "").strip()
    base = f"主角始终是同一个孩子{name}，脸颊圆润、五官自然小巧，年龄外观每页一致"
    if look:
        base += f"，{look}"
    return base + "。"


def build_page_prompt(book: dict, idx: int, feedback: str | None = None) -> str:
    """拼一页的提示词；feedback ∈ {unlike, scene, variation} 时做定向加强。"""
    pages = book.get("pages") or []
    scene = ""
    if 0 <= idx - 1 < len(pages):
        scene = (pages[idx - 1].get("scene") or "").strip()
    if not scene:
        scene = "她安静地待在家里，姿态自然。"
    framing = (FEEDBACK_FRAMING.get(feedback or "") or FRAMING).get(idx, FRAMING[4])
    prefix = FEEDBACK_PREFIX.get(feedback or "", "")

    parts = [
        STYLE_BLOCK,
        character_block(book),
        prefix + scene.rstrip("。；;，, ") + "，" + framing + "。",
        "竖版3:4，主体不贴边。",
        NEGATIVE_BASE,
    ]
    text = "".join(parts)
    if len(text) > config.PROMPT_CHAR_LIMIT and not prefix:
        # 超长时优先精简负面段（保留必须禁止的道具，去掉修饰句）
        parts[4] = (
            "不添加故事里没有的人物、道具、动物；图片内没有任何文字；"
            "不换脸型与服饰；背景简单；不要3D感、大眼、畸形手指。"
        )
        text = "".join(parts)
    return text


def prompt_len(book: dict, idx: int) -> int:
    return len(build_page_prompt(book, idx))
