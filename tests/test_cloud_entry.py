"""Tests for the cloud entry point (main.py)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import main as cloud_main


def _reload() -> None:
    importlib.util.spec_from_file_location(
        "main", Path(cloud_main.__file__)
    )
    importlib.reload(cloud_main)


def test_resolve_token_from_env(monkeypatch, tmp_path):
    monkeypatch.setattr(cloud_main, "ROOT", tmp_path)
    monkeypatch.delenv("KOOK_TOKEN", raising=False)
    monkeypatch.setenv("KOOK_TOKEN", "env-token")
    assert cloud_main.resolve_token() == "env-token"


def test_resolve_token_from_dot_file(monkeypatch, tmp_path):
    monkeypatch.setattr(cloud_main, "ROOT", tmp_path)
    monkeypatch.delenv("KOOK_TOKEN", raising=False)
    (tmp_path / ".env.token").write_text("bare-token", encoding="utf-8")
    assert cloud_main.resolve_token() == "bare-token"


def test_resolve_token_from_dotenv_key(monkeypatch, tmp_path):
    monkeypatch.setattr(cloud_main, "ROOT", tmp_path)
    monkeypatch.delenv("KOOK_TOKEN", raising=False)
    (tmp_path / ".env").write_text(
        '# comment\nKOOK_TOKEN="kv-token"\nOTHER=x\n', encoding="utf-8"
    )
    assert cloud_main.resolve_token() == "kv-token"


def test_env_takes_priority_over_files(monkeypatch, tmp_path):
    monkeypatch.setattr(cloud_main, "ROOT", tmp_path)
    monkeypatch.setenv("KOOK_TOKEN", "env-wins")
    (tmp_path / ".env.token").write_text("file-token", encoding="utf-8")
    assert cloud_main.resolve_token() == "env-wins"


def test_build_bot_uses_absolute_data_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(cloud_main, "ROOT", tmp_path)
    monkeypatch.setenv("KOOK_TOKEN", "env-token")
    bot = cloud_main.build_bot()
    assert str(bot.cache.path) == str(tmp_path / "data" / "password_cache.json")
    assert bot.state_path == tmp_path / "data" / "kook_bot_state.json"
    assert (tmp_path / "data").is_dir()


def test_log_console_override(monkeypatch):
    monkeypatch.delenv("SQUAD_RADIO_LOG_CONSOLE", raising=False)
    assert cloud_main._log_console_override() is None
    for value in ("on", "1", "TRUE", "yes"):
        monkeypatch.setenv("SQUAD_RADIO_LOG_CONSOLE", value)
        assert cloud_main._log_console_override() is True
    for value in ("off", "0", "false", "NO"):
        monkeypatch.setenv("SQUAD_RADIO_LOG_CONSOLE", value)
        assert cloud_main._log_console_override() is False


def test_health_port(monkeypatch):
    monkeypatch.delenv("SQUAD_RADIO_HEALTH_PORT", raising=False)
    assert cloud_main._health_port() is None
    monkeypatch.setenv("SQUAD_RADIO_HEALTH_PORT", "8080")
    assert cloud_main._health_port() == 8080
    monkeypatch.setenv("SQUAD_RADIO_HEALTH_PORT", "0")
    assert cloud_main._health_port() is None
    monkeypatch.setenv("SQUAD_RADIO_HEALTH_PORT", "bad")
    assert cloud_main._health_port() is None


def test_log_max_mb(monkeypatch):
    monkeypatch.delenv("SQUAD_RADIO_MAX_LOG_MB", raising=False)
    assert cloud_main._log_max_mb() == 50.0
    monkeypatch.setenv("SQUAD_RADIO_MAX_LOG_MB", "120")
    assert cloud_main._log_max_mb() == 120.0
    monkeypatch.setenv("SQUAD_RADIO_MAX_LOG_MB", "bad")
    assert cloud_main._log_max_mb() == 50.0


def test_build_bot_exits_without_token(monkeypatch, tmp_path):
    monkeypatch.setattr(cloud_main, "ROOT", tmp_path)
    monkeypatch.delenv("KOOK_TOKEN", raising=False)
    try:
        cloud_main.build_bot()
    except SystemExit as exc:
        assert "KOOK_TOKEN" in str(exc)
    else:
        raise AssertionError("build_bot should exit when no token is available")
