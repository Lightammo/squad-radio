"""Smoke tests for the always-on KOOK '今日密码' listener."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import websocket

from squad_radio.config import PersonaConfig
from squad_radio.kook import KookApiError, KookClient
from squad_radio.kook_bot import (
    REACTION_HEART,
    KookBot,
    build_reply,
    should_reply,
)
from squad_radio.password import (
    PasswordCache,
    PasswordData,
    parse_json_payload,
    parse_reader_payload,
    parse_text_payload,
)
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
    assert "🗺" in text and "🔑" in text and "8865" in text and "ＡＺ３" in text
    assert "零号大坝" in text and "｜" in text
    assert "指挥官" in text and "嘻嘻" not in text


def test_text_fallback_normalizes_az3():
    """备源把 AZ3 写成「AZ3核电站」，解析后必须归一化成 AZ3，否则备源形同虚设。"""
    text = (
        "更新日期: 11月19日每日密码已更新\n密码总数: 6\n\n"
        "地图名称: AZ3核电站\n密码: 3325\n位置描述: 略\n"
        "地图名称: 零号大坝\n密码: 0211\n"
        "地图名称: 长弓溪谷\n密码: 9672\n"
        "地图名称: 巴克什\n密码: 2061\n"
        "地图名称: 航天基地\n密码: 9598\n"
        "地图名称: 潮汐监狱\n密码: 3778\n"
    )
    data = parse_text_payload(text, "2026-11-19", "https://fallback.test")
    assert data is not None
    assert data.entries["AZ3"] == "3325"
    assert data.entries["零号大坝"] == "0211"
    assert "AZ3核电站" not in data.entries

    # 少一张图 -> 整体判为无效，不能拿残缺数据冒充
    assert parse_text_payload(text.replace("地图名称: 巴克什\n密码: 2061\n", ""),
                              "2026-11-19", "x") is None
    # 日期不符 -> 无效，不能拿昨天的密码冒充今天
    assert parse_text_payload(text, "2026-11-20", "x") is None


def test_reader_proxy_fallback_when_primary_times_out(tmp_path, monkeypatch):
    """主源超时（海外节点）时经 reader 代理取同一份 JSON，仍严格校验日期。"""
    raw = {"date": TODAY, "entries": CODES, "sourceMode": "kkrb"}
    wrapped = (
        "Title: \n\nURL Source: https://db.18183.com/x.json\n\n"
        "Published Time: Wed, 18 Nov 2026 16:30:04 GMT\n\n"
        "Markdown Content:\n" + json.dumps(raw, ensure_ascii=False) + "\n"
    )
    assert parse_reader_payload(wrapped) == raw
    assert parse_reader_payload("no json here") is None

    cache = PasswordCache(tmp_path / "pw.json")
    attempted: list[str] = []

    def fake_get(url):
        attempted.append(url)
        if url == cache.url_template.replace("{date}", TODAY):
            raise OSError("timed out")  # 主源直连失败
        if url == cache.reader_prefix + cache.url_template.replace("{date}", TODAY):
            return wrapped  # 代理拿到主源
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(cache, "_get", fake_get)
    data = cache.fetch(TODAY)
    assert data is not None and data.entries == CODES
    assert data.source == cache.url_template.replace("{date}", TODAY)
    assert len(attempted) == 2

    # 代理拿到的 JSON 日期不符时不能冒充当日密码
    wrong = wrapped.replace(TODAY, "2026-11-17")
    monkeypatch.setattr(cache, "_get", lambda url: wrong)
    assert cache.fetch(TODAY) is None


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


def test_add_reaction_posts_correct_payload(monkeypatch):
    """add-reaction 用 msg_id + emoji 走 POST，频道与私聊各自用对端点。"""
    client = KookClient("dummy-token")
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method, path, *, params=None, payload=None):
        calls.append((method, path, payload or {}))
        return {}

    monkeypatch.setattr(client, "_request", fake_request)

    client.add_reaction("msg-1", "❤")
    assert calls[-1] == (
        "POST",
        "/message/add-reaction",
        {"msg_id": "msg-1", "emoji": "❤"},
    )

    client.add_reaction("msg-2", "❤", direct=True)
    assert calls[-1] == (
        "POST",
        "/direct-message/add-reaction",
        {"msg_id": "msg-2", "emoji": "❤"},
    )


def test_handle_event_adds_heart_reaction(monkeypatch):
    """用户发「今日密码」时，除文字回复外还要给该消息加爱心 reaction。"""
    bot = KookBot("dummy-token", bot_user_id="9000000001")
    monkeypatch.setattr(bot.cache, "get", lambda: sample_data())

    sent: list[tuple] = []
    reacted: list[tuple] = []
    monkeypatch.setattr(bot.client, "send_message", lambda *a, **kw: sent.append((a, kw)))
    monkeypatch.setattr(bot.client, "add_reaction", lambda *a, **kw: reacted.append((a, kw)))

    event = {
        "type": 9,
        "channel_type": "GROUP",
        "target_id": "channel-1",
        "author_id": "1000000001",
        "content": "今日密码",
        "msg_id": "msg-xyz",
        "extra": {"author": {"bot": False}},
    }
    bot.handle_event(event)

    assert len(sent) == 1
    assert len(reacted) == 1
    args, kwargs = reacted[0]
    assert args == ("msg-xyz", REACTION_HEART)
    assert kwargs == {"direct": False}
    assert bot.state.replies_sent >= 1


def test_handle_event_skips_reaction_when_no_msg_id(monkeypatch):
    """事件缺 msg_id 时不能崩，也不能调用 add-reaction。"""
    bot = KookBot("dummy-token", bot_user_id="9000000001")
    monkeypatch.setattr(bot.cache, "get", lambda: sample_data())
    monkeypatch.setattr(bot.client, "send_message", lambda *a, **kw: None)

    reacted: list = []
    monkeypatch.setattr(bot.client, "add_reaction", lambda *a, **kw: reacted.append((a, kw)))

    bot.handle_event({
        "type": 9,
        "target_id": "channel-1",
        "author_id": "1000000001",
        "content": "今日密码",
        "extra": {"author": {"bot": False}},
    })
    assert reacted == []


def test_reaction_failure_does_not_break_reply(monkeypatch):
    """加 reaction 报 API 错误时，文字回复仍已完成、不向外抛异常。"""
    bot = KookBot("dummy-token", bot_user_id="9000000001")
    monkeypatch.setattr(bot.cache, "get", lambda: sample_data())
    monkeypatch.setattr(bot.client, "send_message", lambda *a, **kw: None)

    def fail_reaction(*_a, **_kw):
        raise KookApiError(403, "no permission")

    monkeypatch.setattr(bot.client, "add_reaction", fail_reaction)

    bot.handle_event({
        "type": 9,
        "channel_type": "GROUP",
        "target_id": "channel-1",
        "author_id": "1000000001",
        "content": "今日密码",
        "msg_id": "msg-xyz",
        "extra": {"author": {"bot": False}},
    })  # 不应抛异常
