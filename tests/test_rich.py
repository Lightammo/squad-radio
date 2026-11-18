"""Tests for KMarkdown rich formatting and KOOK asset helper."""
from __future__ import annotations

from datetime import datetime, timezone

from squad_radio.models import Broadcast
from squad_radio.rich import (
    DEFAULT_IMAGES,
    RichStyle,
    format_broadcast,
    format_password_card,
    thumb,
)
from squad_radio.password import PasswordData


def test_thumb_uses_same_url_as_label():
    url = "https://img.kookapp.cn/attachments/x.png"
    assert thumb(url) == f"[{url}]({url})"
    assert thumb(None) == ""


def test_price_broadcast_has_thumbnail_title_and_action():
    b = Broadcast(
        group_id="g",
        text="指挥官，行情图纸刷新了哦。钛合金 涨了 18%，当前 8.2 万。",
        event_key="price:钛合金:123",
        priority=2,
        actions=["订阅 钛合金"],
    )
    out = format_broadcast(b)
    assert DEFAULT_IMAGES["market"] in out
    assert "**📈 行情异动播报**" in out
    assert "`(spl)" not in out and "(spl)" in out
    assert "快捷指令：" in out and "`订阅 钛合金`" in out


def test_red_broadcast_converts_plain_mention_to_met_syntax():
    b = Broadcast(
        group_id="g",
        text="@10001 在长弓溪谷摸到了曼德尔超算单元，估值 280 万。",
        event_key="red:10001:曼德尔超算单元:1",
        priority=3,
        target_user_id="10001",
    )
    out = format_broadcast(b)
    assert "(met)10001(met)" in out
    assert "@10001" not in out
    assert DEFAULT_IMAGES["red"] in out


def test_style_can_disable_images_and_splash():
    b = Broadcast(
        group_id="g",
        text="测试内容",
        event_key="task:u:制造台:1",
        priority=2,
        actions=[],
    )
    plain = format_broadcast(b, RichStyle(show_thumbnail=False, show_splash=False))
    assert "http" not in plain
    assert "(spl)" not in plain
    assert "**🔧 特勤处完工**" in plain


def test_custom_images_override_defaults():
    b = Broadcast(group_id="g", text="内容", event_key="price:x:1", priority=2)
    custom = {"market": "https://img.kookapp.cn/custom.png"}
    out = format_broadcast(b, RichStyle(images=custom))
    assert "custom.png" in out
    assert DEFAULT_IMAGES["market"] not in out


def test_password_card_structure():
    card = format_password_card(
        ["零号大坝：`8865`", "长弓溪谷：`4565`"],
        title="今日作战密码 · 2026-11-18",
        mention="(met)10001(met)",
        footnote="指挥官，请以游戏内为准哦。",
    )
    assert card.startswith("[https://")
    assert "(met)10001(met) **今日作战密码 · 2026-11-18**" in card
    assert "(spl)" in card
    assert "---" in card
    assert "> 指挥官，请以游戏内为准哦。" in card
