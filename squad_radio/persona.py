"""Architect persona layer for Squad Radio.

The persona is applied at delivery time, so rules and command handlers can stay
focused on facts while this module decides how the Architect would say them.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .config import PersonaConfig
from .models import Broadcast, Event, EventType


class Tone(str, Enum):
    CELEBRATE = "celebrate"
    INFO = "info"
    REMIND = "remind"
    ALERT = "alert"
    SUCCESS = "success"
    ERROR = "error"
    NEUTRAL = "neutral"
    GREETING = "greeting"


@dataclass(frozen=True)
class PersonaContext:
    """Semantic hints used to choose appropriate Architect phrasing."""

    tone: Tone = Tone.NEUTRAL
    key: str = ""
    event_type: EventType | None = None
    mention: bool = False
    reunion: bool = False


_OPENINGS: dict[Tone, list[str]] = {
    Tone.CELEBRATE: [
        "指挥官，幸运值超标了呢！",
        "嘻嘻，指挥官，这可是加倍的幸运哦！",
        "指挥官，我真是超——幸运呢！",
    ],
    Tone.INFO: [
        "指挥官，今日蓝图铺好了呢。",
        "指挥官，请过目——",
        "早八施工简报，指挥官请查收哦。",
    ],
    Tone.REMIND: [
        "指挥官，施工完毕～",
        "指挥官，收菜时间到哦。",
        "指挥官，有个小工程完工了呢。",
    ],
    Tone.ALERT: [
        "指挥官，行情图纸刷新了哦。",
        "指挥官，请注意——",
        "指挥官，数据有动静呢。",
    ],
    Tone.SUCCESS: [
        "收到，指挥官！",
        "图纸已登记，指挥官。",
        "指挥官，这就安排上哦。",
    ],
    Tone.ERROR: [
        "指挥官，图纸对不上呢……",
        "指挥官，这里好像需要重画一下。",
        "啊啦，指挥官，参数似乎歪了一点。",
    ],
    Tone.NEUTRAL: [
        "指挥官，说明书在这里哦。",
        "是指挥官呀，请讲。",
        "指挥官，我听着呢。",
    ],
    Tone.GREETING: [
        "铁血工造的建筑师，正式加入！",
        "指挥官，我们又相遇了呢！",
        "嘻嘻，指挥官，好久不见哦！",
    ],
}

_SUFFIXES: dict[Tone, list[str]] = {
    Tone.CELEBRATE: [
        "这波施工记录我记下了哦。",
        "恭喜恭喜，蓝图上又多一笔呢。",
        "加倍的幸运，要好好收着哦。",
    ],
    Tone.INFO: [
        "今天也请多关照哦。",
        "作战准备就绪，指挥官。",
        "图纸已就位，随时开工呢。",
    ],
    Tone.REMIND: [
        "别让产能白给哦。",
        "记得签收，嘻嘻。",
        "我先把工具收好，指挥官。",
    ],
    Tone.ALERT: [
        "要不要动手，由您决定呢。",
        "建议先看一眼再施工哦。",
        "我把数据摆这儿了，指挥官。",
    ],
    Tone.SUCCESS: [
        "嘻嘻，交给我吧。",
        "这就开工哦，指挥官。",
        "登记完毕，请放心呢。",
    ],
    Tone.ERROR: [
        "再试一次吧，我等着哦。",
        "请核对一下参数呢。",
        "重画一张就好，别急哦。",
    ],
    Tone.NEUTRAL: [
        "嘻嘻，随时为您施工。",
        "需要什么尽管说呢。",
        "我这边随时待命，指挥官。",
    ],
    Tone.GREETING: [
        "这可是加倍的幸运哦！",
        "我真是超——幸运呢，嘻嘻！",
        "以后也一起施工吧，指挥官！",
    ],
}

_EXTRA_TICS = ["嘻嘻", "呢", "哦", "超——幸运", "加倍"]


def _pick(variants: list[str], key: str) -> str:
    seed = sum(ord(char) for char in key) if key else 0
    return variants[seed % len(variants)]


def _already_styled(text: str) -> bool:
    return text.startswith("指挥官") or text.startswith("铁血工造") or "嘻嘻" in text


def _attach(core: str, tail: str) -> str:
    if not tail:
        return core
    if core and core[-1] not in "。！？!?~～…":
        return f"{core}。{tail}"
    return f"{core}{tail}"


class ArchitectPersona:
    """Wrap outgoing text in Architect's voice when the tone allows it."""

    def __init__(self, config: PersonaConfig | None = None):
        self.config = config or PersonaConfig()

    def context_for_event(self, event: Event, broadcast: Broadcast) -> PersonaContext:
        if event.type == EventType.RED_DROP:
            tone = Tone.CELEBRATE
        elif event.type == EventType.TASK_COMPLETED:
            tone = Tone.REMIND
        elif event.type == EventType.DAILY_PASSWORD:
            tone = Tone.INFO
        elif "跌" in broadcast.text:
            tone = Tone.ALERT
        elif "涨" in broadcast.text or "涨幅" in broadcast.text:
            tone = Tone.ALERT
        else:
            tone = Tone.INFO
        return PersonaContext(
            tone=tone,
            key=broadcast.event_key or f"{event.type.value}:{event.subject}",
            event_type=event.type,
            mention=bool(broadcast.target_user_id),
        )

    def context_for_command(self, text: str, reply: str) -> PersonaContext:
        if any(word in text for word in ("你好", "您好", "在吗", "早安", "晚上好")):
            tone, reunion = Tone.GREETING, True
        elif any(
            word in reply
            for word in ("格式", "参数", "未识别", "请在群里", "需要用户", "没有找到")
        ):
            tone, reunion = Tone.ERROR, False
        elif any(word in reply for word in ("已订阅", "已退订", "已开启", "已取消")):
            tone, reunion = Tone.SUCCESS, False
        else:
            tone, reunion = Tone.NEUTRAL, False
        return PersonaContext(tone=tone, key=text.strip() or reply, reunion=reunion)

    def render(self, text: str, context: PersonaContext | None = None) -> str:
        if not self.config.enabled or self.config.intensity == "off":
            return text
        ctx = context or PersonaContext()
        if not text.strip():
            return text
        if _already_styled(text):
            return text
        if ctx.reunion:
            ctx = PersonaContext(
                tone=Tone.GREETING,
                key=ctx.key,
                event_type=ctx.event_type,
                mention=ctx.mention,
                reunion=True,
            )

        core = text.strip()
        key = ctx.key or core
        opening = _pick(_OPENINGS[ctx.tone], key)
        suffix = _pick(_SUFFIXES[ctx.tone], key + ":tail")

        if self.config.intensity == "light":
            return _attach(core, suffix)
        if self.config.intensity == "full":
            tic = _pick(_EXTRA_TICS, key + ":tic")
            if ctx.tone in {Tone.ALERT, Tone.ERROR}:
                tic = "哦"
            return _attach(f"{opening}{core}", f"{suffix}{tic}")
        return _attach(f"{opening}{core}", suffix)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "style": self.config.style,
            "intensity": self.config.intensity,
            "address": self.config.address,
        }
