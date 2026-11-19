"""Smoke checks for the g.aitags.cn manufacture board parser."""
from __future__ import annotations

from typing import Any

from squad_radio.manufacture import format_manufacture_broadcast, parse_manufacture_page

_PAGE = """
<p>数据自动更新于：11-20 02:52 · 已过滤亏损与零收益物品 · 接口每 30 分钟更新</p>
<div class="df-level-block hidden" data-level="1">
  <span class="text-sm font-bold text-white truncate">旧等级</span>
  <ul class="df-card-list" data-limit="1"></ul>
</div>
<div class="df-level-block " data-level="3">
  <span class="text-sm font-bold text-white truncate">技术中心</span>
  <ul class="df-card-list" data-limit="2">
    <li class="df-row" data-hour="900" data-total="9000" title="A — 制造时长 10 小时 · 解锁 Lv.3 · 未扣手续费 1 · 手续费 2">
      <span class="df-rank">1</span>
      <div class="text-sm font-bold text-slate-900 dark:text-white truncate leading-5">低小时收益</div>
      <div class="text-xs text-slate-400 truncate leading-4 h-4" title="瞄具 · 10小时">瞄具 · 10小时</div>
    </li>
    <li class="df-row" data-hour="1200" data-total="6000" title="B — 制造时长 5 小时 · 解锁 Lv.3 · 未扣手续费 1 · 手续费 3">
      <span class="df-rank">2</span>
      <div class="text-sm font-bold text-slate-900 dark:text-white truncate leading-5">高小时收益</div>
      <div class="text-xs text-slate-400 truncate leading-4 h-4" title="弹药 · 5小时">弹药 · 5小时</div>
    </li>
  </ul>
</div>
<script>window.switchLevel = function () {};</script>
"""


class _FakeClient:
    def __init__(self):
        self.calls: list[tuple[Any, ...]] = []

    def send_message(self, target_id, content, msg_type=9, nonce=None):
        self.calls.append((target_id, content, msg_type, nonce))
        return {"msg_id": "fake"}


def test_hourly_scheduler_dedupes(monkeypatch, tmp_path):
    from squad_radio import manufacture_bot

    monkeypatch.setattr(
        manufacture_bot,
        "fetch_manufacture_recommendations",
        lambda **kwargs: ("11-20 02:52", []),
    )
    client = _FakeClient()
    scheduler = manufacture_bot.ManufactureScheduler(
        client, "chan", state_path=tmp_path / "state.json"
    )

    assert scheduler.send_hourly("2026-11-20T03") is True
    assert scheduler.send_hourly("2026-11-20T03") is False
    assert len(client.calls) == 1
    assert client.calls[0][3] == "manufacture:2026-11-20T03:3:hour:1"


def test_manufacture_parse_and_format():
    update, recs = parse_manufacture_page(_PAGE, level=3, rank_type="hour", top_per_department=2)

    assert update == "11-20 02:52"
    assert [rec.item for rec in recs] == ["高小时收益", "低小时收益"]
    assert recs[0].department == "技术中心"
    assert recs[0].category == "弹药"
    assert recs[0].duration_hours == "5小时"
    assert recs[0].hourly_profit == 1200

    text = format_manufacture_broadcast(update, recs, level=3, rank_type="hour")
    assert "特勤处制造推荐 · 3级" in text
    assert "`1,200/h`" in text
    assert "高小时收益" in text
