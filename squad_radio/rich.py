"""KMarkdown text formatting for KOOK broadcasts.

KOOK KMarkdown supports bold, inline code, quotes, dividers, emoji, mentions
``(met)id(met)`` and spoilers ``(spl)..(spl)``. There is no inline image
syntax (``![alt](url)``) and no table syntax, so messages are text-only cards;
the password list uses a fenced monospace code block as an aligned table.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from .models import Broadcast

_HEADERS: dict[str, str] = {
    "price": "📈 行情异动播报",
    "red": "💎 高价值物资",
    "password": "🔑 今日作战密码",
    "task": "🔧 特勤处完工",
}

_SPLASHES: dict[str, str] = {
    "price": "(spl)先别急着all in，看看群里怎么说(spl)",
    "red": "(spl)群里先安静三秒，恭喜就完事了(spl)",
    "password": "(spl)记不住没关系，随时在群里喊「今日密码」(spl)",
    "task": "(spl)产能这种东西，放着是会过期的哦(spl)",
}


def _kind_of(event_key: str) -> str:
    head = event_key.split(":", 1)[0]
    return head if head in _HEADERS else "info"


def _as_mention(text: str, user_id: str | None) -> str:
    """Convert plain '@123' style mentions into KOOK (met) syntax."""
    if not user_id:
        return text
    return text.replace(f"@{user_id}", f"(met){user_id}(met)")


@dataclass
class RichStyle:
    """Toggles for how decorative the formatting should be."""

    show_splash: bool = True
    show_actions: bool = True


def format_broadcast(broadcast: Broadcast, style: RichStyle | None = None) -> str:
    """Render a Broadcast as a decorated KMarkdown text card.

    The broadcast text is already persona-voiced by the engine, so this layer
    only adds structure: a titled header, the body, a spoiler easter-egg and
    the quick-action hint.
    """
    style = style or RichStyle()
    kind = _kind_of(broadcast.event_key)
    title = _HEADERS.get(kind, "📻 战地播报")

    lines = [f"**{title}**", _as_mention(broadcast.text.strip(), broadcast.target_user_id)]
    if style.show_splash and kind in _SPLASHES:
        lines.append(_SPLASHES[kind])

    parts = [line for line in lines if line]
    if style.show_actions and broadcast.actions:
        actions = " ｜ ".join(f"`{item}`" for item in broadcast.actions)
        parts.append("---")
        parts.append(f"快捷指令：{actions}")
    return "\n".join(parts)


def _display_width(text: str) -> int:
    """Width in monospace cells: East Asian wide/fullwidth chars take two."""
    total = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        total += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return total


def _pad_right(text: str, width: int) -> str:
    """Right-pad with spaces to the requested display width."""
    return text + " " * max(0, width - _display_width(text))


def format_password_table(entries: dict[str, str]) -> str:
    """Render map/password pairs as an aligned table in a fenced code block.

    KOOK KMarkdown has no native table syntax, but it does support fenced code
    blocks rendered in a monospace font. Padding cells by *display* width keeps
    the columns aligned even with Chinese map names mixed with ASCII digits.
    """
    if not entries:
        return ""

    name_width = max(_display_width(name) for name in entries)
    code_width = max(_display_width(code) for code in entries.values())
    name_width = max(name_width, _display_width("地图"))
    code_width = max(code_width, _display_width("密码"))

    def row(name: str, code: str) -> str:
        return f"{_pad_right(name, name_width)}  {_pad_right(code, code_width)}"

    divider = f"{'-' * name_width}  {'-' * code_width}"
    body = [row("地图", "密码"), divider]
    body.extend(row(name, code) for name, code in entries.items())
    return "```\n" + "\n".join(body) + "\n```"


def format_password_card(
    lines: list[str],
    *,
    title: str,
    mention: str | None = None,
    footnote: str = "数据每天早上更新，以游戏内为准哦。",
    style: RichStyle | None = None,
) -> str:
    """Build the always-on '今日密码' reply card (KMarkdown)."""
    style = style or RichStyle()
    out: list[str] = []

    header = f"**{title}**"
    if mention:
        header = f"{mention} {header}"
    out.append(header)
    out.extend(lines)
    if style.show_splash:
        out.append(_SPLASHES["password"])
    out.append("---")
    out.append(f"> {footnote}")
    return "\n".join(out)
