"""Smoke tests for the Architect persona layer."""
from __future__ import annotations

from datetime import datetime, timezone

from squad_radio.broadcasters import Broadcaster
from squad_radio.config import (
    AppConfig,
    DefaultsConfig,
    GroupConfig,
    NoiseConfig,
    PersonaConfig,
)
from squad_radio.engine import RadioEngine
from squad_radio.models import Broadcast, Event, EventType
from squad_radio.persona import ArchitectPersona, PersonaContext, Tone
from squad_radio.rules import default_rules
from squad_radio.storage import Storage

FIXED = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)


class SpyBroadcaster(Broadcaster):
    def __init__(self) -> None:
        self.messages: list[Broadcast] = []

    def send(self, broadcast: Broadcast) -> None:
        self.messages.append(broadcast)


def make_engine(tmp_path):
    config = AppConfig(
        db_path=str(tmp_path / "test.db"),
        noise=NoiseConfig(quiet_hours=[], daily_cap=12),
        defaults=DefaultsConfig(red_min_value_wan=100.0),
        groups=[GroupConfig(id="g", subscriptions=[])],
    )
    spy = SpyBroadcaster()
    engine = RadioEngine(config, Storage(config.db_path), default_rules(), spy)
    engine.seed_subscriptions()
    return engine, spy


def test_persona_voices_broadcasts_and_commands(tmp_path):
    """播报和群内指令都带建筑师语气，且问候不会被当成未识别指令。"""
    engine, spy = make_engine(tmp_path)
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
    assert len(spy.messages) == 1
    assert "指挥官" in spy.messages[0].text
    assert "@10001" in spy.messages[0].text

    greeting = engine.handle_command("你好", "g", "u")
    assert "未识别指令" not in greeting and "又相遇" in greeting

    subscribed = engine.handle_command("订阅 钛合金 12 45", "g", "u")
    assert "指挥官" in subscribed and "已订阅" in subscribed


def test_tone_varies_by_semantics_and_can_be_disabled():
    """语气按语义区分（出红庆祝 / 行情不嬉笑），且可整体关闭。"""
    persona = ArchitectPersona()

    red = persona.context_for_event(
        Event(
            type=EventType.RED_DROP,
            subject="曼德尔超算单元",
            value=280,
            group_id="g",
            user_id="10001",
            ts=FIXED,
        ),
        Broadcast(group_id="g", text="@10001 摸到了曼德尔超算单元"),
    )
    assert red.tone is Tone.CELEBRATE
    red_text = persona.render("@10001 摸到了曼德尔超算单元", red)
    assert "指挥官" in red_text
    assert any(word in red_text for word in ("幸运", "恭喜", "蓝图"))

    alert = persona.context_for_event(
        Event(
            type=EventType.PRICE_SNAPSHOT,
            subject="钛合金",
            value=8.2,
            group_id="g",
            ts=FIXED,
        ),
        Broadcast(group_id="g", text="钛合金 涨了 18%，当前 8.2 万。"),
    )
    assert alert.tone is Tone.ALERT
    assert "嘻嘻" not in persona.render("钛合金 涨了 18%，当前 8.2 万。", alert)

    disabled = ArchitectPersona(PersonaConfig(enabled=False))
    assert disabled.render("原文", PersonaContext(tone=Tone.CELEBRATE)) == "原文"
