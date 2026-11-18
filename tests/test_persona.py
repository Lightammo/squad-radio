"""Tests for the Architect persona layer."""
from __future__ import annotations

from datetime import datetime, timezone

from squad_radio.broadcasters import Broadcaster
from squad_radio.config import (
    AppConfig,
    DefaultsConfig,
    GroupConfig,
    NoiseConfig,
    PersonaConfig,
    SubscriptionRule,
    load_config,
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


def make_persona_engine(tmp_path):
    config = AppConfig(
        db_path=str(tmp_path / "persona.db"),
        noise=NoiseConfig(quiet_hours=[], daily_cap=12),
        defaults=DefaultsConfig(red_min_value_wan=100.0),
        groups=[GroupConfig(id="g", subscriptions=[])],
    )
    storage = Storage(config.db_path)
    engine = RadioEngine(config, storage, default_rules(), SpyBroadcaster())
    engine.seed_subscriptions()
    return config, storage, engine


def test_celebrate_tone_for_red_drop():
    persona = ArchitectPersona()
    ctx = persona.context_for_event(
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
    assert ctx.tone is Tone.CELEBRATE
    text = persona.render("@10001 摸到了曼德尔超算单元", ctx)
    assert "指挥官" in text
    assert any(word in text for word in ("幸运", "恭喜", "蓝图"))


def test_alert_tone_avoids_giggling():
    persona = ArchitectPersona()
    ctx = persona.context_for_event(
        Event(type=EventType.PRICE_SNAPSHOT, subject="钛合金", value=8.2, group_id="g", ts=FIXED),
        Broadcast(group_id="g", text="钛合金 涨了 18%，当前 8.2 万。"),
    )
    assert ctx.tone is Tone.ALERT
    text = persona.render("钛合金 涨了 18%，当前 8.2 万。", ctx)
    assert "指挥官" in text
    assert "嘻嘻" not in text


def test_greeting_command_uses_reunion_phrase():
    persona = ArchitectPersona()
    ctx = persona.context_for_command("你好", "未识别指令：你好")
    text = persona.render("未识别指令：你好", ctx)
    assert "指挥官" in text
    assert any(word in text for word in ("正式加入", "又相遇", "好久不见"))


def test_engine_greeting_is_not_unknown_command(tmp_path):
    _, _, engine = make_persona_engine(tmp_path)
    reply = engine.handle_command("你好", "g", "u")
    assert "未识别指令" not in reply
    assert "又相遇" in reply


def test_error_command_uses_apology_phrase():
    persona = ArchitectPersona()
    ctx = persona.context_for_command("订阅", "格式：订阅 物品 [涨幅阈值]")
    text = persona.render("格式：订阅 物品 [涨幅阈值]", ctx)
    assert any(word in text for word in ("图纸", "重画", "核对"))


def test_persona_can_be_disabled():
    persona = ArchitectPersona(PersonaConfig(enabled=False))
    assert persona.render("原文", PersonaContext(tone=Tone.CELEBRATE)) == "原文"


def test_no_double_styling():
    persona = ArchitectPersona()
    assert persona.render("指挥官，已订阅钛合金", PersonaContext(tone=Tone.SUCCESS)) == "指挥官，已订阅钛合金"


def test_config_loads_persona_section(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[persona]\nenabled = false\nintensity = "full"\naddress = "长官"\n',
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.persona.enabled is False
    assert config.persona.intensity == "full"
    assert config.persona.address == "长官"


def test_engine_voices_broadcasts_and_commands(tmp_path):
    config = AppConfig(
        db_path=str(tmp_path / "test.db"),
        noise=NoiseConfig(quiet_hours=[], daily_cap=12),
        defaults=DefaultsConfig(red_min_value_wan=100.0),
        groups=[GroupConfig(id="g", subscriptions=[])],
    )
    storage = Storage(config.db_path)
    spy = SpyBroadcaster()
    engine = RadioEngine(config, storage, default_rules(), spy)
    engine.seed_subscriptions()

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

    reply = engine.handle_command("订阅 钛合金 12 45", "g", "u")
    assert "指挥官" in reply
    assert "已订阅" in reply
    assert storage.get_subscriptions("g")[0].threshold_pct == 12
