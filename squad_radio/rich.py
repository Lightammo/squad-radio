"""KMarkdown text formatting for KOOK broadcasts.

KOOK KMarkdown supports bold, inline code, quotes, dividers, emoji, mentions
``(met)id(met)`` and spoilers ``(spl)..(spl)``. There is no inline image
syntax (``![alt](url)``) and no table syntax, so messages are text-only cards;
the password list is a code-block table aligned with fullwidth padding.
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import Broadcast

_HEADERS: dict[str, str] = {
    "price": "📈 行情异动播报",
    "red": "💎 高价值物资",
    "password": "🔑 今日作战密码",
    "task": "🔧 特勤处完工",
}

_SPLASHES: dict[str, str] = {
    "price": "小贴士 ~ (spl)先别急着all in，看看群里怎么说(spl)",
    "red": "小贴士 ~ (spl)群里先安静三秒，恭喜就完事了(spl)",
    "password": "小贴士 ~ (spl)记不住没关系，随时在群里喊「今日密码」(spl)",
    "task": "小贴士 ~ (spl)产能这种东西，放着是会过期的哦(spl)",
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


def _to_fullwidth(s: str) -> str:
    """Convert ASCII visible chars (``!``..``~``) to fullwidth (+0xFEE0)."""
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in s)


def format_password_table(pw: dict[str, str]) -> str:
    """Render a code-block table aligned with fullwidth spaces and a ｜ divider.

    Map names are converted to fullwidth so a halfwidth name such as ``AZ3``
    occupies the same display width as the same number of CJK glyphs. Every
    row is padded to the same character count on the left of ``｜``, which is
    what actually makes the columns line up in KOOK's proportional code font.
    The header carries emoji; data rows stay plain.
    """
    if not pw:
        return ""

    names = [_to_fullwidth(name) for name in pw]
    head_label = "地图 🗺"
    # 名字与表头一起取最大宽度，保证 emoji 表头也能与数据行对齐。
    name_w = max([len(name) for name in names] + [len(head_label)])

    lines = [f"{head_label.ljust(name_w, '　')}｜密码🔑"]

    for name, code in zip(names, pw.values()):
        lines.append(f"{name.ljust(name_w, '　')}｜{code}")

    return "```\n" + "\n".join(lines) + "\n```"


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
