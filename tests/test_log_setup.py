"""Tests for logging setup."""
from __future__ import annotations

import logging
from datetime import datetime

import os
import time

from squad_radio.log_setup import (
    _CleaningFileHandler,
    build_log_filename,
    cleanup_old_logs,
    configure_logging,
)


def test_log_filename_has_project_timestamp_and_pid():
    name = build_log_filename(datetime(2026, 11, 18, 22, 30, 5), pid=4321)
    assert name == "squad-radio_20261118-223005_4321.log"


def test_configure_logging_always_writes_file_even_when_console_off(tmp_path):
    log_path = configure_logging(tmp_path / "logs", foreground=False)
    assert log_path.exists()
    assert log_path.parent.name == "logs"
    assert log_path.name.startswith("squad-radio_")

    logging.getLogger("probe").info("后台日志测试")
    log_path.parent  # keep reference
    assert "后台日志测试" in log_path.read_text(encoding="utf-8")


def test_configure_logging_console_on_adds_stream_handler(tmp_path):
    configure_logging(tmp_path / "logs", foreground=True)
    handlers = logging.getLogger().handlers
    assert any(isinstance(h, logging.FileHandler) for h in handlers)
    assert any(
        type(h) is logging.StreamHandler and not isinstance(h, logging.FileHandler)
        for h in handlers
    )


def _make_log(directory, name, size, mtime):
    path = directory / name
    path.write_bytes(b"x" * size)
    os.utime(path, (mtime, mtime))
    return path


def test_cleanup_removes_oldest_until_under_limit_and_keeps_active(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    now = time.time()
    oldest = _make_log(logs, "squad-radio_old_1_1.log", 30, now - 300)
    middle = _make_log(logs, "squad-radio_mid_2_2.log", 30, now - 200)
    active = _make_log(logs, "squad-radio_new_3_3.log", 10, now - 100)
    _make_log(logs, "other_app.log", 1000, now - 400)  # 非本项目日志不动

    # 本项目三个文件共 70 bytes；上限 40 => 删最旧(30)后剩 40，停
    removed = cleanup_old_logs(logs, max_bytes=40, keep=active)

    assert removed == [oldest]
    assert oldest.exists() is False
    assert middle.exists() and active.exists()
    assert (logs / "other_app.log").exists()


def test_cleanup_does_nothing_when_under_limit(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    one = _make_log(logs, "squad-radio_a_1_1.log", 10, time.time())
    assert cleanup_old_logs(logs, max_bytes=100) == []
    assert one.exists()


def test_cleanup_never_deletes_active_file_even_if_oversized(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    active = _make_log(logs, "squad-radio_active_1_1.log", 500, time.time())
    assert cleanup_old_logs(logs, max_bytes=10, keep=active) == []
    assert active.exists()


def test_configure_logging_clears_history_on_startup(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    _make_log(logs, "squad-radio_ancient_1_1.log", 2 * 1024 * 1024, time.time() - 1000)

    configure_logging(logs, foreground=False, max_log_mb=1)

    assert not (logs / "squad-radio_ancient_1_1.log").exists()


def test_cleaning_handler_is_installed(tmp_path):
    configure_logging(tmp_path / "logs", foreground=False, max_log_mb=5)
    assert any(isinstance(h, _CleaningFileHandler) for h in logging.getLogger().handlers)
