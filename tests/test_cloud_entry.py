"""Smoke tests for the cloud entry point (main.py)."""
from __future__ import annotations

import main as cloud_main


def test_resolve_token_and_build_bot(monkeypatch, tmp_path):
    """token 能从 env / 文件读取，env 优先；无 token 直接退出；数据路径为绝对路径。"""
    monkeypatch.setattr(cloud_main, "ROOT", tmp_path)
    monkeypatch.delenv("KOOK_TOKEN", raising=False)

    token_file = tmp_path / ".env.token"
    token_file.write_text("bare-token", encoding="utf-8")
    assert cloud_main.resolve_token() == "bare-token"

    token_file.unlink()
    (tmp_path / ".env").write_text(
        '# comment\nKOOK_TOKEN="kv-token"\nOTHER=x\n', encoding="utf-8"
    )
    assert cloud_main.resolve_token() == "kv-token"

    monkeypatch.setenv("KOOK_TOKEN", "env-wins")
    assert cloud_main.resolve_token() == "env-wins"

    bot = cloud_main.build_bot()
    assert str(bot.cache.path) == str(tmp_path / "data" / "password_cache.json")
    assert bot.state_path == tmp_path / "data" / "kook_bot_state.json"

    monkeypatch.delenv("KOOK_TOKEN", raising=False)
    (tmp_path / ".env").unlink()
    try:
        cloud_main.build_bot()
    except SystemExit as exc:
        assert "KOOK_TOKEN" in str(exc)
    else:
        raise AssertionError("build_bot should exit when no token is available")


def test_env_overrides(monkeypatch):
    """云端环境变量解析：终端日志、健康端口、日志上限。"""
    for name in (
        "SQUAD_RADIO_LOG_CONSOLE",
        "SQUAD_RADIO_HEALTH_PORT",
        "SQUAD_RADIO_MAX_LOG_MB",
    ):
        monkeypatch.delenv(name, raising=False)

    assert cloud_main._log_console_override() is None
    monkeypatch.setenv("SQUAD_RADIO_LOG_CONSOLE", "on")
    assert cloud_main._log_console_override() is True
    monkeypatch.setenv("SQUAD_RADIO_LOG_CONSOLE", "off")
    assert cloud_main._log_console_override() is False

    assert cloud_main._health_port() is None
    monkeypatch.setenv("SQUAD_RADIO_HEALTH_PORT", "8080")
    assert cloud_main._health_port() == 8080
    monkeypatch.setenv("SQUAD_RADIO_HEALTH_PORT", "bad")
    assert cloud_main._health_port() is None

    assert cloud_main._log_max_mb() == 50.0
    monkeypatch.setenv("SQUAD_RADIO_MAX_LOG_MB", "120")
    assert cloud_main._log_max_mb() == 120.0
