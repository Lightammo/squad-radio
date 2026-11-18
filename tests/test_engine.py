"""Smoke tests for the core trigger engine: alerts, big-red drops, commands."""
from __future__ import annotations

from datetime import datetime, timezone

from squad_radio.broadcasters import Broadcaster
from squad_radio.config import (
    AppConfig,
    DefaultsConfig,
    GroupConfig,
    NoiseConfig,
    SubscriptionRule,
)
from squad_radio.engine import RadioEngine
from squad_radio.models import Broadcast, Event, EventType
from squad_radio.rules import default_rules
from squad_radio.storage import Storage

FIXED = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)


class SpyBroadcaster(Broadcaster):
    def __init__(self) -> None:
        self.messages: list[Broadcast] = []

    def send(self, broadcast: Broadcast) -> None:
        self.messages.append(broadcast)


def make_engine(tmp_path, *, daily_cap: int = 12, subscriptions=None):
    config = AppConfig(
        db_path=str(tmp_path / "test.db"),
        noise=NoiseConfig(quiet_hours=[], daily_cap=daily_cap),
        defaults=DefaultsConfig(red_min_value_wan=100.0),
        groups=[GroupConfig(id="g", subscriptions=subscriptions or [])],
    )
    spy = SpyBroadcaster()
    engine = RadioEngine(config, Storage(config.db_path), default_rules(), spy)
    engine.seed_subscriptions()
    return config, engine, spy


def price_event(value: float, minute: int) -> Event:
    return Event(
        type=EventType.PRICE_SNAPSHOT,
        subject="钛合金",
        value=value,
        group_id="g",
        ts=FIXED.replace(minute=minute),
    )


def test_price_alert_and_dedupe(tmp_path):
    """物价异动能触发，且同一事件不重复刷屏。"""
    _, engine, spy = make_engine(
        tmp_path, subscriptions=[SubscriptionRule("钛合金", 15, 30)]
    )
    engine.process(price_event(6.95, 0))
    engine.process(price_event(8.2, 20))
    engine.process(price_event(8.2, 22))  # 重复事件应被抑制

    assert len(spy.messages) == 1
    text = spy.messages[0].text
    assert "钛合金" in text and "18%" in text
    assert spy.messages[0].actions == ["订阅 钛合金"]


def test_red_drop_mentions_user(tmp_path):
    """大红播报 @ 出红者，且高优先级能穿透每日上限。"""
    _, engine, spy = make_engine(tmp_path, daily_cap=0)
    engine.process(
        Event(
            type=EventType.RED_DROP,
            subject="曼德尔超算单元",
            value=280,
            group_id="g",
            user_id="10001",
            ts=FIXED,
            payload={"map": "长弓溪谷"},
        )
    )
    assert len(spy.messages) == 1
    assert "@10001" in spy.messages[0].text
    assert "280" in spy.messages[0].text
    assert spy.messages[0].priority == 3


def test_subscription_command(tmp_path):
    """群内订阅指令能写进规则库。"""
    config, engine, _ = make_engine(tmp_path)
    reply = engine.handle_command("订阅 钛合金 12 45", "g", "u")
    assert "已订阅" in reply
    rules = Storage(config.db_path).get_subscriptions("g")
    assert len(rules) == 1
    assert (rules[0].item, rules[0].threshold_pct, rules[0].window_minutes) == (
        "钛合金",
        12,
        45,
    )
