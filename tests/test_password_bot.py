"""Tests for password cache and the always-on KOOK listener rules."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from squad_radio.config import LOCAL_TZ, PersonaConfig
from squad_radio.kook_bot import build_reply, should_reply
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


def test_parse_json_payload_validates_date_and_maps():
    raw = {"date": TODAY, "entries": CODES}
    parsed = parse_json_payload(raw, TODAY, "https://example.test")
    assert parsed is not None
    assert parsed.entries["AZ3"] == "2430"

    assert parse_json_payload(raw, "2026-11-17", "https://example.test") is None
    assert parse_json_payload({"date": TODAY, "entries": {"零号大坝": "8865"}}, TODAY, "x") is None


def test_cache_reads_same_day_without_fetch(tmp_path, monkeypatch):
    path = tmp_path / "password.json"
    path.write_text(json.dumps(sample_data().to_dict(), ensure_ascii=False), encoding="utf-8")
    cache = PasswordCache(path)

    def fail_fetch(_date):
        raise AssertionError("same-day cache should not refetch")

    monkeypatch.setattr(cache, "fetch", fail_fetch)
    data = cache.get(now=datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc))
    assert data is not None
    assert data.entries == CODES


def test_cache_refreshes_on_new_date(tmp_path, monkeypatch):
    path = tmp_path / "password.json"
    path.write_text(json.dumps(sample_data().to_dict(), ensure_ascii=False), encoding="utf-8")
    cache = PasswordCache(path)
    monkeypatch.setattr(cache, "fetch", lambda date: None)

    data = cache.get(now=datetime(2026, 11, 18, 16, 10, tzinfo=timezone.utc))
    assert data is None


def test_should_reply_only_for_real_user_password_message():
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


def test_reply_mentions_asker_and_uses_persona():
    persona = ArchitectPersona(PersonaConfig())
    text = build_reply(sample_data(), "1000000001", persona)
    assert "(met)1000000001(met)" in text
    assert TODAY in text
    assert "8865" in text
    assert "AZ3" in text
    assert "指挥官" in text
    assert "嘻嘻" not in text


def test_reply_without_password_uses_error_tone():
    persona = ArchitectPersona(PersonaConfig())
    text = build_reply(None, "1000000001", persona)
    assert "(met)1000000001(met)" in text
    assert "还没查到" in text
    assert "嘻嘻" not in text
