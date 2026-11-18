"""Smoke tests for logging: file naming, background writes, auto-cleanup."""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime

from squad_radio.log_setup import (
    _CleaningFileHandler,
    build_log_filename,
    cleanup_old_logs,
    configure_logging,
)


def _make_log(directory, name, size, mtime):
    path = directory / name
    path.write_bytes(b"x" * size)
    os.utime(path, (mtime, mtime))
    return path


def test_filename_and_background_writes_file(tmp_path):
    """文件名 = 项目名+启动时间戳+PID；后台静默运行也必须落盘。"""
    assert build_log_filename(datetime(2026, 11, 18, 22, 30, 5), pid=4321) == (
        "squad-radio_20261118-223005_4321.log"
    )
    log_path = configure_logging(tmp_path / "logs", foreground=False)
    assert log_path.exists() and log_path.parent.name == "logs"
    assert log_path.name.startswith("squad-radio_")

    logging.getLogger("probe").info("后台日志测试")
    assert "后台日志测试" in log_path.read_text(encoding="utf-8")


def test_cleanup_removes_oldest_and_keeps_active(tmp_path):
    """超上限删最旧，当前活跃日志与非本项目日志都不动。"""
    logs = tmp_path / "logs"
    logs.mkdir()
    now = time.time()
    oldest = _make_log(logs, "squad-radio_old_1_1.log", 30, now - 300)
    middle = _make_log(logs, "squad-radio_mid_2_2.log", 30, now - 200)
    active = _make_log(logs, "squad-radio_new_3_3.log", 10, now - 100)
    other = _make_log(logs, "other_app.log", 1000, now - 400)

    # 本项目三个文件共 70 bytes；上限 40 => 删最旧(30)后剩 40，停
    assert cleanup_old_logs(logs, max_bytes=40, keep=active) == [oldest]
    assert not oldest.exists()
    assert middle.exists() and active.exists() and other.exists()

    # 目录里只剩活跃文件、且它远超上限时也不删
    solo = tmp_path / "solo"
    solo.mkdir()
    only_active = _make_log(solo, "squad-radio_active_1_1.log", 500, time.time())
    assert cleanup_old_logs(solo, max_bytes=1, keep=only_active) == []
    assert only_active.exists()


def test_startup_cleanup_and_handlers(tmp_path):
    """启动先清历史，且装上终端/清理两种 handler。"""
    logs = tmp_path / "logs"
    logs.mkdir()
    ancient = _make_log(
        logs, "squad-radio_ancient_1_1.log", 2 * 1024 * 1024, time.time() - 1000
    )

    configure_logging(logs, foreground=True, max_log_mb=1)

    assert not ancient.exists()
    handlers = logging.getLogger().handlers
    assert any(isinstance(h, _CleaningFileHandler) for h in handlers)
    assert any(
        type(h) is logging.StreamHandler and not isinstance(h, logging.FileHandler)
        for h in handlers
    )
