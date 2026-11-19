"""Tests for the daily 00:00 password broadcast scheduler."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from squad_radio.config import LOCAL_TZ
from squad_radio.password import PasswordData
from squad_radio.password_bot import PasswordScheduler, build_scheduler_from_env

TODAY = "2026-11-21"
CODES = {
    "零号大坝": "0624", "长弓溪谷": "0416", "巴克什": "0017",
    "航天基地": "0283", "潮汐监狱": "0216", "AZ3": "0820",
}


def _data(date=TODAY, codes=None) -> PasswordData:
    return PasswordData(
        date=date, entries=codes or CODES, source="test", fetched_at="x"
    )


class FakeCache:
    def __init__(self, data):
        self.data = data

    def get(self):
        return self.data


class FakeClient:
    def __init__(self):
        self.calls = []

    def send_message(self, channel, content, msg_type=9, nonce=None):
        self.calls.append({
            "channel": channel, "content": content,
            "msg_type": msg_type, "nonce": nonce,
        })
        return {"msg_id": f"msg-{len(self.calls)}"}


def _scheduler(tmp_path, *, cache_data=_data(), **kw):
    client = FakeClient()
    sched = PasswordScheduler(
        client, "2352172414970176", FakeCache(cache_data),
        state_path=tmp_path / "state.json", **kw,
    )
    return sched, client


def test_send_daily_posts_card_with_nonce_and_marks_state(tmp_path):
    sched, client = _scheduler(tmp_path)
    assert sched.send_daily(TODAY) is True
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["channel"] == "2352172414970176"
    assert call["msg_type"] == 9
    assert call["nonce"] == f"daily-password:{TODAY}"
    assert TODAY in call["content"] and "零号大坝" in call["content"]
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["last_date"] == TODAY
    assert state["last_msg_id"] == "msg-1"


def test_send_daily_skips_same_day_even_after_restart(tmp_path):
    sched1, client1 = _scheduler(tmp_path)
    sched1.send_daily(TODAY)
    # 模拟进程重启：全新 scheduler 读同一状态文件
    sched2, client2 = _scheduler(tmp_path)
    assert sched2.send_daily(TODAY) is False
    assert client2.calls == []


def test_send_daily_refuses_stale_or_missing_data(tmp_path):
    # 数据源还停留在昨天 -> 不发送、不写状态
    sched, client = _scheduler(tmp_path, cache_data=_data(date="2026-11-20"))
    assert sched.send_daily(TODAY) is False
    assert client.calls == []
    assert not (tmp_path / "state.json").exists()

    # 完全没有数据 -> 同样不发送
    sched2, client2 = _scheduler(tmp_path, cache_data=None)
    assert sched2.send_daily(TODAY) is False
    assert client2.calls == []


def test_next_target_respects_hour_minute():
    sched, _ = _scheduler(Path("/tmp"), hour=6, minute=30)
    now = datetime(2026, 11, 21, 3, 0, tzinfo=LOCAL_TZ)
    assert sched._next_target(now).hour == 6
    assert sched._next_target(now).minute == 30


def test_build_scheduler_env_switch(tmp_path, monkeypatch):
    monkeypatch.delenv("SQUAD_RADIO_PASSWORD_CHANNEL", raising=False)
    assert build_scheduler_from_env("t", tmp_path) is None

    monkeypatch.setenv("SQUAD_RADIO_PASSWORD_CHANNEL", "off")
    assert build_scheduler_from_env("t", tmp_path) is None

    monkeypatch.setenv("SQUAD_RADIO_PASSWORD_CHANNEL", "2352172414970176")
    monkeypatch.setenv("SQUAD_RADIO_PASSWORD_HOUR", "6")
    monkeypatch.setenv("SQUAD_RADIO_PASSWORD_MINUTE", "5")
    sched = build_scheduler_from_env("t", tmp_path)
    assert sched is not None
    assert sched.channel_id == "2352172414970176"
    assert sched.hour == 6 and sched.minute == 5
    assert sched.state_path.name == "password_daily_state.json"
