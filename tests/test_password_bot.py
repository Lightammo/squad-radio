"""Smoke tests for the always-on KOOK '今日密码' listener."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import websocket

from squad_radio.config import PersonaConfig
from squad_radio.kook_bot import KookBot, build_reply, should_reply
from squad_radio.password import PasswordCache, PasswordData, parse_json_payload
from squad_radio.persona import ArchitectPersona

TODAY = "2026-11-18"
CODES = {
    "零号大坝": "8865",
    "长弓溪谷": "4565",
    "巴克什": "6468",
    "航天基地": "8572",
    "潮汐监狱": "2161",
    "AZ3": "2430",
}


def sample_data() -> PasswordData:
    return PasswordData(
        date=TODAY,
        entries=CODES,
        source="test",
        fetched_at="2026-11-18T00:05:00+08:00",
    )


def test_trigger_and_reply():
    """只回真人密码消息，回复 @ 提问人、带 ❤️ 与对齐表格。"""
    event = {
        "type": 9,
        "target_id": "channel-1",
        "author_id": "1000000001",
        "content": "今日密码",
        "extra": {"author": {"bot": False}},
    }
    assert should_reply(event, "9000000001", "今日密码") is True
    assert should_reply({**event, "author_id": "9000000001"}, "9000000001", "今日密码") is False
    assert should_reply({**event, "type": 1, "content": "早上好"}, "9000000001", "今日密码") is False
    assert should_reply({**event, "extra": {"author": {"bot": True}}}, None, "今日密码") is False

    text = build_reply(sample_data(), "1000000001", ArchitectPersona(PersonaConfig()))
    assert "(met)1000000001(met) ❤️" in text
    assert TODAY in text and "```" in text
    assert "地图" in text and "密码" in text
    assert "8865" in text and "AZ3" in text
    assert "指挥官" in text and "嘻嘻" not in text


def test_password_daily_cache(tmp_path, monkeypatch):
    """上游数据校验、当日只读缓存、跨零点刷新。"""
    raw = {"date": TODAY, "entries": CODES}
    assert parse_json_payload(raw, TODAY, "https://example.test").entries["AZ3"] == "2430"
    assert parse_json_payload(raw, "2026-11-17", "x") is None
    assert parse_json_payload({"date": TODAY, "entries": {"零号大坝": "8865"}}, TODAY, "x") is None

    path = tmp_path / "password.json"
    path.write_text(json.dumps(sample_data().to_dict(), ensure_ascii=False), encoding="utf-8")

    cache = PasswordCache(path)

    def fail_fetch(_date):
        raise AssertionError("same-day cache should not refetch")

    monkeypatch.setattr(cache, "fetch", fail_fetch)
    same_day = cache.get(now=datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc))
    assert same_day is not None and same_day.entries == CODES

    next_day = PasswordCache(path)
    monkeypatch.setattr(next_day, "fetch", lambda date: None)
    assert next_day.get(now=datetime(2026, 11, 18, 16, 10, tzinfo=timezone.utc)) is None


def test_connect_recovers_from_expired_session(tmp_path, monkeypatch):
    """握手遇到 40107 必须丢弃旧 session 重新连接，不能死循环 resume。"""
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"sn": 42, "session_id": "old-session"}), encoding="utf-8"
    )
    bot = KookBot("dummy-token", state_path=state_path)
    monkeypatch.setattr(
        bot.client, "gateway", lambda compress=0: {"url": "wss://gateway.test/ws"}
    )

    urls: list[str] = []
    responses = iter(
        [
            json.dumps({"s": 5, "d": {"code": 40107, "err": "Session expired"}}),
            json.dumps({"s": 1, "d": {"code": 0, "session_id": "fresh-session"}}),
        ]
    )

    class FakeWS:
        def __init__(self, url, **_kwargs):
            urls.append(url)

        def recv(self):
            return next(responses)

        def close(self):
            pass

        def settimeout(self, _value):
            pass

    monkeypatch.setattr(websocket, "create_connection", FakeWS)

    bot._load_state()
    assert bot._connect() is not None
    assert len(urls) == 2
    assert "resume=1" in urls[0] and "resume=1" not in urls[1]
    assert bot.session_id == "fresh-session" and bot.last_sn == 0
    assert json.loads(state_path.read_text(encoding="utf-8"))["session_id"] == "fresh-session"


def test_reply_without_password_uses_error_tone():
    """密码没查到时也要 @ + ❤️，并用道歉语气而不是嬉笑。"""
    text = build_reply(None, "1000000001", ArchitectPersona(PersonaConfig()))
    assert "(met)1000000001(met) ❤️" in text
    assert "还没查到" in text and "嘻嘻" not in text


def test_graceful_shutdown(tmp_path, monkeypatch):
    """stop() 幂等、信号处理器置位、run() 退出时保存状态。"""
    import signal as _signal

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"sn": 7, "session_id": "s-7"}), encoding="utf-8")
    bot = KookBot("dummy-token", state_path=state_path, bot_user_id="9000000001")

    bot.stop()
    bot.stop()
    assert bot.stopping is True

    bot._install_signal_handlers()
    try:
        handler = _signal.getsignal(_signal.SIGTERM)
        assert callable(handler)
        handler(_signal.SIGTERM, None)
    finally:
        bot._restore_signal_handlers()
    assert bot.stopping is True

    runner = KookBot("dummy-token", state_path=state_path, bot_user_id="9000000001")
    monkeypatch.setattr(runner, "refresh_password", lambda: None)

    class FakeWS:
        def settimeout(self, _v):
            pass

        def recv(self):
            runner.stop()
            raise websocket.WebSocketTimeoutException()

        def close(self):
            pass

    monkeypatch.setattr(runner, "_connect", lambda: FakeWS())
    runner.run()
    assert runner.stopping is True
    assert json.loads(state_path.read_text(encoding="utf-8"))["sn"] == 7
