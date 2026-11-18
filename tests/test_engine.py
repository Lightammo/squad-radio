"""Unit tests for trigger rules and noise control."""
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


def make_engine(
    tmp_path,
    *,
    quiet_hours: list[str] | None = None,
    daily_cap: int = 12,
    subscriptions: list[SubscriptionRule] | None = None,
):
    config = AppConfig(
        db_path=str(tmp_path / "test.db"),
        noise=NoiseConfig(quiet_hours=quiet_hours or [], daily_cap=daily_cap),
        defaults=DefaultsConfig(red_min_value_wan=100.0),
        groups=[GroupConfig(id="g", subscriptions=subscriptions or [])],
    )
    storage = Storage(config.db_path)
    spy = SpyBroadcaster()
    engine = RadioEngine(config, storage, default_rules(), spy)
    engine.seed_subscriptions()
    return config, storage, engine, spy


def price_event(subject: str, value: float, ts: datetime) -> Event:
    return Event(
        type=EventType.PRICE_SNAPSHOT,
        subject=subject,
        value=value,
        group_id="g",
        ts=ts,
    )


def test_price_spike_broadcasts(tmp_path):
    _, _, engine, spy = make_engine(
        tmp_path, subscriptions=[SubscriptionRule("钛合金", 15, 30)]
    )

    engine.process(price_event("钛合金", 6.95, FIXED))
    engine.process(price_event("钛合金", 8.2, FIXED.replace(minute=20)))

    assert len(spy.messages) == 1
    assert "钛合金" in spy.messages[0].text
    assert "18%" in spy.messages[0].text
    assert spy.messages[0].actions == ["订阅 钛合金"]


def test_duplicate_event_is_suppressed(tmp_path):
    _, _, engine, spy = make_engine(
        tmp_path, subscriptions=[SubscriptionRule("钛合金", 15, 30)]
    )

    engine.process(price_event("钛合金", 6.95, FIXED))
    engine.process(price_event("钛合金", 8.2, FIXED.replace(minute=20)))
    engine.process(price_event("钛合金", 6.95, FIXED.replace(minute=21)))
    engine.process(price_event("钛合金", 8.2, FIXED.replace(minute=22)))

    assert len(spy.messages) == 1


def test_high_priority_red_bypasses_daily_cap(tmp_path):
    _, _, engine, spy = make_engine(tmp_path, daily_cap=0)

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


def test_quiet_hours_suppress_low_priority_only(tmp_path):
    _, _, engine, spy = make_engine(tmp_path, quiet_hours=["00:00-23:59"])

    engine.process(price_event("钛合金", 6.95, FIXED))
    engine.process(price_event("钛合金", 8.2, FIXED.replace(minute=20)))
    assert spy.messages == []

    engine.process(
        Event(
            type=EventType.RED_DROP,
            subject="曼德尔超算单元",
            value=280,
            group_id="g",
            user_id="10001",
            ts=FIXED.replace(minute=21),
        )
    )
    assert len(spy.messages) == 1


def test_subscription_command_updates_rules(tmp_path):
    _, storage, engine, _ = make_engine(tmp_path)

    reply = engine.handle_command("订阅 钛合金 12 45", "g", "u")

    assert "已订阅" in reply
    rules = storage.get_subscriptions("g")
    assert len(rules) == 1
    assert rules[0].item == "钛合金"
    assert rules[0].threshold_pct == 12
    assert rules[0].window_minutes == 45


def test_optout_blocks_red_broadcast(tmp_path):
    _, _, engine, spy = make_engine(tmp_path)

    engine.handle_command("免打扰", "g", "10001")
    engine.process(
        Event(
            type=EventType.RED_DROP,
            subject="曼德尔超算单元",
            value=280,
            group_id="g",
            user_id="10001",
            ts=FIXED,
        )
    )

    assert spy.messages == []
