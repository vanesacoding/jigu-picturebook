"""把家长的口语输入整理成五页叙事结构（V0 不依赖大模型，规则可读可改）。

叙事结构（固定，但文案不套模板）：
  P1 封面 / P2 故事开始 / P3 发生的事情 / P4 最值得记住的细节 / P5 结尾与家长感受

产出必须满足两条硬约束（源自 Seedream 实验报告）：
1. 每页画面描述要落到"具体身体动作 + 具体空间关系"，抽象动词会被模型翻译成道具。
2. 不添加输入里没有的人物、道具、情节；不确定的一律不写。

家长可以在预览页修改全部文字与画面描述，所以这里的职责是给一个诚实的初稿，
而不是猜出一个漂亮故事。
"""

from __future__ import annotations

import re

CLOTHING = [
    "围巾", "外套", "毛衣", "裙子", "睡衣", "背带裤", "帽子", "马甲", "卫衣",
    "短袖", "T恤", "斗篷", "发卡", "头绳", "包被", "连体衣",
]
COLORS = [
    "紫色", "粉色", "红色", "蓝色", "黄色", "绿色", "白色", "灰色", "黑色",
    "杏色", "米色", "橙色", "藏青", "浅蓝", "浅黄", "浅粉", "奶白", "奶黄色",
]
STATE_WORDS = ["发烧", "生病", "感冒", "不舒服", "咳嗽", "哭", "睡着", "睡了", "下雨", "不能出门", "住院"]
ACTION_WORDS = ["玩", "做", "画", "唱", "跑", "爬", "跳", "去", "看", "拿", "用", "吃", "抱", "穿", "戴", "搭"]
SPEECH_PATTERN = re.compile(r"[「“\"']([^」”\"']{2,20})[」”\"']")

SPLIT_PATTERN = re.compile(r"[，,。；;！!？?\n]+")

QUOTE_RE = re.compile(r"[「“\"']([^」”\"']*)[」”\"']")
LEAD_WORDS = ["今天", "昨天", "上午", "下午", "晚上", "中午", "早上", "刚才"]


def _clauses(text: str) -> list[str]:
    return [c.strip() for c in SPLIT_PATTERN.split(text or "") if c.strip()]


def _replace_self(text: str, name: str) -> str:
    """家长口述里的「我」指家长，「宝宝」指孩子。

    引号内的内容不动：孩子说的「我是国王先生」里的「我」不能改成「妈妈」，
    这是第一人称的台词，不是家长自指。
    """
    if not text:
        return ""
    spans: list[str] = []

    def _keep(m: re.Match[str]) -> str:
        spans.append(m.group(0))
        return f"\x00{len(spans) - 1}\x00"

    tmp = QUOTE_RE.sub(_keep, text)
    tmp = tmp.replace("宝宝", name).replace("孩子", name)
    tmp = tmp.replace("我的", "妈妈的").replace("我", "妈妈")
    tmp = tmp.replace(f"{name}{name}", name)
    for i, span in enumerate(spans):
        tmp = tmp.replace(f"\x00{i}\x00", span.replace("宝宝", name))
    return tmp


def _strip_lead(clause: str, name: str) -> str:
    """去掉分句开头的「今天」「开心」等，避免和模板前缀重复。"""
    s = clause.strip()
    changed = True
    while changed:
        changed = False
        for w in LEAD_WORDS + [name]:
            if w and s.startswith(w):
                s = s[len(w):].lstrip("，, ")
                changed = True
    return s


def _to_corner_quotes(text: str) -> str:
    return QUOTE_RE.sub(lambda m: f"「{m.group(1)}」", text)


def _tidy(sentence: str) -> str:
    s = sentence.strip().strip("，,")
    if s and s[-1] not in "。！？":
        s += "。"
    return s


def _pick(clauses: list[str], words: list[str]) -> list[str]:
    return [c for c in clauses if any(w in c for w in words)]


def extract_character(*texts: str, name: str = "") -> str:
    """从家长描述里提取要固定的衣物/配饰，供每页复用以抑制漂移。

    返回形如「紫色围巾包住头部并绕在颈部，穿浅奶白色上衣」的描述片段。
    提不到就退回中性的"穿浅色家居服"，不虚构。
    """
    blob = "".join(t or "" for t in texts)
    found: list[str] = []
    for item in CLOTHING:
        if item not in blob:
            continue
        idx = blob.find(item)
        color = ""
        for c in COLORS:
            if c in blob[max(0, idx - 6): idx + len(item) + 2]:
                color = c
                break
        found.append(color + item)

    pieces = []
    if any("围巾" in f for f in found):
        scarf = next(f for f in found if "围巾" in f)
        if any(w in blob for w in ["包头", "包住头", "裹住头", "包在头上", "裹头", "绕在颈", "绕脖"]):
            pieces.append(f"{scarf}包住头部并绕在颈部")
        else:
            pieces.append(f"{scarf}围在颈部")
    others = [f for f in found if "围巾" not in f]
    if others:
        pieces.append("穿" + others[0])
    if not pieces:
        pieces.append("穿浅色家居服")
    return "，".join(pieces)


def structure(event: str, feeling: str = "", detail: str = "", name: str = "宝宝") -> dict:
    """生成五页初稿：{title, subtitle, character, pages:[{text, scene}]}"""
    name = (name or "宝宝").strip() or "宝宝"
    ev = _replace_self(event, name)
    fe = _replace_self(feeling, name)
    de = _replace_self(detail, name)

    clauses = _clauses(ev)
    state_cl = _pick(clauses, STATE_WORDS)
    action_cl = [c for c in _pick(clauses, ACTION_WORDS) if c not in state_cl]
    rest_cl = [c for c in clauses if c not in state_cl and c not in action_cl]

    quote = ""
    m = SPEECH_PATTERN.search(detail or "") or SPEECH_PATTERN.search(event or "")
    if m:
        quote = m.group(1).strip()

    # ---- 书名 ----
    if quote:
        tail = "" if quote[-1] in "。！？!?" else "！"
        title = f"《{quote}{tail}》"
    elif action_cl:
        title = f"《{name}的小小一天》"
    else:
        title = f"《{name}的一天》"
    subtitle = f"{name}的成长小故事"

    # ---- P2 故事开始 ----
    if state_cl:
        p2 = f"今天，{name}{_strip_lead(state_cl[0], name)}"
        extra = [_strip_lead(c, name) for c in state_cl[1:] if len(c) <= 8]
        if extra:
            p2 += f"，{extra[0]}"
        p2 = _tidy(p2)
    elif rest_cl:
        p2 = _tidy(f"今天，{name}{_strip_lead(rest_cl[0], name)}")
    else:
        p2 = _tidy(f"今天，{name}在家里")

    # ---- P3 发生的事情 ----
    body = action_cl or [c for c in clauses if c not in state_cl] or rest_cl
    if body:
        joined = "，".join(body[:2])
        p3 = _tidy(f"{name}{joined}" if not joined.startswith(name) else joined)
    else:
        p3 = _tidy(f"{name}在家待了一整天")

    # ---- P4 最值得记住的细节：优先取台词那一句，其余留给 P5 收尾 ----
    de_clauses = [_to_corner_quotes(c) for c in _clauses(de)]
    quote_cl = [c for c in de_clauses if SPEECH_PATTERN.search(c)]
    insight_cl = [c for c in de_clauses if c not in quote_cl]
    if quote_cl:
        p4 = _tidy(quote_cl[0])
    elif de_clauses:
        p4 = _tidy(de_clauses[0])
    elif quote:
        p4 = _tidy(f"{name}说：「{quote}」")
    else:
        p4 = _tidy(f"这一刻，{name}的样子让人想记很久")

    # ---- P5 结尾与家长感受 ----
    p5_parts = [_tidy(fe)] if fe else []
    p5_parts += [_tidy(x) for x in insight_cl]
    if quote and not any("居然" in x or "竟然" in x for x in p5_parts):
        p5_parts.append(_tidy(f"{name}居然会说「{quote}」呢！"))
    if not p5_parts:
        p5_parts.append(_tidy(f"{name}的样子，就是今天最想记住的事"))
    p5 = "".join(p5_parts)

    character = extract_character(event, detail, feeling, name=name)
    pages = [
        {"text": title, "scene": f"她侧头看向画面外，{character.split('，')[0]}，姿态安静自然"},
        {"text": p2, "scene": f"她待在家里，{character.split('，')[0]}，神情安静、略显没精神，双手自然放在身旁"},
        {"text": p3, "scene": f"她坐着，{character.split('，')[0]}，微微歪头，一只手抬起做轻小的动作"},
        {"text": p4, "scene": f"她正面看向画面，{character.split('，')[0]}，露出自然笑容，正在开口说话的瞬间"},
        {"text": p5, "scene": f"她靠坐着，{character.split('，')[0]}，笑得眼睛弯起，画面温暖安静，无其他人物"},
    ]
    return {"title": title, "subtitle": subtitle, "character": character, "pages": pages}


if __name__ == "__main__":  # 本地自检，不调用任何接口
    demo = structure(
        event="宝宝今天发烧了，不能出门，在家用我的围巾扮演阿拉伯的国王和公主玩。",
        feeling="我觉得她好可爱。",
        detail="宝宝说“我是国王先生”，她居然知道国王是先生。",
        name="开心",
    )
    import json

    print(json.dumps(demo, ensure_ascii=False, indent=2))
