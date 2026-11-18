"""Logging setup for Squad Radio.

A UTF-8 log file is *always* written under <project>/logs, so a detached or
background process never loses its records. When the process runs in the
foreground (interactive terminal, or explicitly requested), records are also
echoed to the terminal for live viewing.

Log file name: squad-radio_<YYYYmmdd-HHMMSS>_<pid>.log
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT_NAME = "squad-radio"
DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DEFAULT_MAX_LOG_MB = 50.0
_CLEANUP_INTERVAL_SEC = 5.0


def build_log_filename(now: datetime | None = None, pid: int | None = None) -> str:
    """Build a log file name from project name, start timestamp and process id."""
    stamp = now or datetime.now()
    proc = os.getpid() if pid is None else pid
    return f"{PROJECT_NAME}_{stamp:%Y%m%d-%H%M%S}_{proc}.log"


def is_foreground() -> bool:
    """True when stdout/stderr is attached to an interactive terminal."""
    try:
        return bool(sys.stdout.isatty() or sys.stderr.isatty())
    except (AttributeError, ValueError):
        return False


def _log_files(logs_dir: str | Path) -> list[Path]:
    """Log files managed by this project, oldest modification time first."""
    directory = Path(logs_dir)
    if not directory.is_dir():
        return []
    files = [
        path
        for path in directory.glob(f"{PROJECT_NAME}_*.log")
        if path.is_file()
    ]
    return sorted(files, key=lambda path: path.stat().st_mtime)


def cleanup_old_logs(
    logs_dir: str | Path,
    max_bytes: int,
    *,
    keep: str | Path | None = None,
) -> list[Path]:
    """Delete oldest log files until total size is within ``max_bytes``.

    The file currently being written (``keep``) is never deleted. Returns the
    list of files that were removed, oldest first.
    """
    if max_bytes <= 0:
        return []
    keep_path = Path(keep).resolve() if keep is not None else None
    files = [f for f in _log_files(logs_dir) if f.resolve() != keep_path]
    total = sum(path.stat().st_size for path in files)

    removed: list[Path] = []
    for path in files:
        if total <= max_bytes:
            break
        try:
            size = path.stat().st_size
            path.unlink()
            total -= size
            removed.append(path)
        except OSError:
            continue
    return removed


class _CleaningFileHandler(logging.FileHandler):
    """File handler that enforces a directory-wide size cap on log files.

    Checks at most every few seconds while logging, so a long-running process
    keeps pruning the oldest files as its log grows, without stat-ing the disk
    on every single record.
    """

    def __init__(self, *args, logs_dir: str | Path, max_bytes: int, **kwargs):
        super().__init__(*args, **kwargs)
        self._logs_dir = Path(logs_dir)
        self._max_bytes = max_bytes
        self._last_check = time.monotonic()

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        now = time.monotonic()
        if now - self._last_check >= _CLEANUP_INTERVAL_SEC:
            self._last_check = now
            cleanup_old_logs(self._logs_dir, self._max_bytes, keep=self.baseFilename)


def configure_logging(
    logs_dir: str | Path | None = None,
    *,
    foreground: bool | None = None,
    level: int = logging.INFO,
    max_log_mb: float = DEFAULT_MAX_LOG_MB,
) -> Path:
    """Configure the root logger: always a file handler, optional console.

    ``foreground=None`` auto-detects via :func:`is_foreground`. Pass True/False
    to force console echo on/off regardless of TTY detection. Log files in
    ``logs_dir`` are kept under ``max_log_mb`` in total; when exceeded the
    oldest files are deleted (the active file is preserved). Returns the path
    of the log file that was created.
    """
    directory = Path(logs_dir) if logs_dir is not None else ROOT / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / build_log_filename()
    echo_console = is_foreground() if foreground is None else foreground
    max_bytes = int(max_log_mb * 1024 * 1024)

    # 启动时先清一遍历史堆积，再创建新日志；新日志是当前文件，不会被删。
    cleanup_old_logs(directory, max_bytes)

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(DEFAULT_LOG_FORMAT)

    file_handler = _CleaningFileHandler(
        log_path,
        logs_dir=directory,
        max_bytes=max_bytes,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if echo_console:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    logging.getLogger(__name__).info(
        "日志已启用：%s（终端输出：%s，上限：%gMB）",
        log_path,
        "开" if echo_console else "关",
        max_log_mb,
    )
    return log_path
