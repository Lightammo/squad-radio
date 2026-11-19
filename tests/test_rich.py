"""Smoke tests for KMarkdown text formatting."""
from __future__ import annotations

from squad_radio.models import Broadcast
from squad_radio.rich import (
    format_broadcast,
    format_password_card,
    format_password_table,
)


def test_password_table():
    """密码表：代码块内全角补齐 + ｜ 单分隔符，｜ 左侧字符数一致即对齐。"""
    table = format_password_table(
        {"零号大坝": "8865", "长弓溪谷": "4565", "AZ3": "2430"}
    )
    assert table.startswith("```\n") and table.endswith("\n```")
    lines = table.splitlines()[1:-1]
    # 每行恰好一个全角分隔符
    assert all(line.count("｜") == 1 for line in lines)
    # 对齐的真正断言：｜ 左侧字符数（含全角空格）全部相等
    assert len({len(line.split("｜")[0]) for line in lines}) == 1
    # 表头：含地图/密码，emoji 只在表头
    assert "地图" in lines[0].split("｜")[0] and "密码" in lines[0].split("｜")[1]
    assert "🗺" in lines[0] and "🔑" in lines[0]
    assert all("🗺" not in line for line in lines[1:])
    # 中文名不变；半角 AZ3 转全角
    assert any("零号大坝" in line and "8865" in line for line in lines)
    assert any("ＡＺ３" in line and "2430" in line for line in lines)
    assert format_password_table({}) == ""


def test_password_card():
    """密码消息卡片：保留代码块、剧透、分割线、脚注，无图片。"""
    table = format_password_table({"零号大坝": "8865"})
    card = format_password_card(
        [table],  # 线上就是把这个表格作为一行塞进卡片
        title="今日作战密码 · 2026-11-18",
        mention="(met)10001(met)",
        footnote="指挥官，请以游戏内为准哦。",
    )
    assert card.startswith("(met)10001(met) **今日作战密码 · 2026-11-18**")
    assert "```" in card and "🗺" in card
    assert "(spl)" in card and "---" in card
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
