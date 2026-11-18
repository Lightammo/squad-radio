"""Smoke tests for KMarkdown text formatting."""
from __future__ import annotations

from squad_radio.models import Broadcast
from squad_radio.rich import (
    _display_width,
    format_broadcast,
    format_password_card,
    format_password_table,
)


def test_password_card_and_table():
    """密码消息是纯文字卡片，表格按显示宽度对齐。"""
    table = format_password_table(
        {"零号大坝": "8865", "长弓溪谷": "4565", "AZ3": "2430"}
    )
    assert table.startswith("```\n") and table.endswith("\n```")
    body = table.splitlines()[1:-1]
    assert body[0].startswith("地图") and "密码" in body[0]
    assert "---" in body[1]
    assert any("零号大坝" in row and "8865" in row for row in body)
    # 中文名按 2 列补齐后，各行显示宽度一致
    assert len({_display_width(row) for row in body if "---" not in row}) == 1
    assert "![" not in table and "http" not in table
    assert format_password_table({}) == ""

    card = format_password_card(
        [table],  # 线上就是把这个表格作为一行塞进卡片
        title="今日作战密码 · 2026-11-18",
        mention="(met)10001(met)",
        footnote="指挥官，请以游戏内为准哦。",
    )
    assert card.startswith("(met)10001(met) **今日作战密码 · 2026-11-18**")
    assert "```" in card and "(spl)" in card and "---" in card
    assert "> 指挥官，请以游戏内为准哦。" in card
    assert "![" not in card and "http" not in card


def test_broadcast_card_uses_kmarkdown():
    """通用播报卡片：加粗标题、剧透、原生 @、无图片。"""
    price = format_broadcast(
        Broadcast(
            group_id="g",
            text="指挥官，行情图纸刷新了哦。钛合金 涨了 18%，当前 8.2 万。",
            event_key="price:钛合金:123",
            priority=2,
            actions=["订阅 钛合金"],
        )
    )
    assert "**📈 行情异动播报**" in price
    assert "(spl)" in price and "`订阅 钛合金`" in price

    red = format_broadcast(
        Broadcast(
            group_id="g",
            text="@10001 在长弓溪谷摸到了曼德尔超算单元，估值 280 万。",
            event_key="red:10001:曼德尔超算单元:1",
            priority=3,
            target_user_id="10001",
        )
    )
    assert "(met)10001(met)" in red and "@10001" not in red
    assert "**💎 高价值物资**" in red
    assert "![" not in price and "http" not in price
