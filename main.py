"""Cloud entry point for Squad Radio (Altare / any Python host).

Reads KOOK_TOKEN from the environment or a local .env / .env.token file,
resolves cache and state paths relative to this file (so it works regardless
of the host's working directory), and runs the always-on password listener.

Run with:  python main.py
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from squad_radio.kook_bot import KookBot
from squad_radio.log_setup import configure_logging
from squad_radio.password import PasswordCache

# main.py 就躺在项目根目录，所以 ROOT 是它自己的目录（不是上一级）。
# 允许用 SQUAD_RADIO_HOME 覆盖，方便代码与数据分开放置。
_DEFAULT_ROOT = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("SQUAD_RADIO_HOME") or _DEFAULT_ROOT).resolve()


def _read_token_file(path: Path) -> str:
    """Read a bare token file, or KEY=VALUE pairs from a .env file."""
    if not path.is_file():
        return ""
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return ""
    if "=" in raw and not raw.startswith("1/"):
        values: dict[str, str] = {}
        for line in raw.splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
        return values.get("KOOK_TOKEN", "")
    return raw


def resolve_token() -> str:
    """Token priority: environment variable > .env.token > .env file."""
    token = (os.environ.get("KOOK_TOKEN") or "").strip()
    if token:
        return token
    for name in (".env.token", ".env"):
        token = _read_token_file(ROOT / name)
        if token:
            return token
    return ""


def build_bot(health_port: int | None = None, health_host: str = "127.0.0.1") -> KookBot:
    """Construct the bot with cloud-safe absolute paths."""
    token = resolve_token()
    if not token:
        raise SystemExit(
            "缺少 KOOK_TOKEN：请在托管平台设置环境变量 KOOK_TOKEN，"
            "或在项目根目录放一个 .env.token / .env 文件。"
        )
    data_dir = ROOT / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return KookBot(
        token,
        password_cache=PasswordCache(data_dir / "password_cache.json"),
        state_path=data_dir / "kook_bot_state.json",
        health_port=health_port,
        health_host=health_host,
    )


def _log_console_override() -> bool | None:
    """Allow forcing terminal echo on/off via env var on cloud hosts."""
    value = (os.environ.get("SQUAD_RADIO_LOG_CONSOLE") or "").strip().lower()
    if value in ("on", "1", "true", "yes"):
        return True
    if value in ("off", "0", "false", "no"):
        return False
    return None


def _log_max_mb() -> float:
    """Max total log size in MB, configurable via env var on cloud hosts."""
    value = (os.environ.get("SQUAD_RADIO_MAX_LOG_MB") or "").strip()
    if not value:
        return 50.0
    try:
        return float(value)
    except ValueError:
        return 50.0


def _health_port() -> int | None:
    """Optional health endpoint port from env; None disables it."""
    value = (os.environ.get("SQUAD_RADIO_HEALTH_PORT") or "").strip()
    if not value:
        return None
    try:
        port = int(value)
        return port if 0 < port < 65536 else None
    except ValueError:
        return None


def _health_host() -> str:
    """健康端点默认只监听回环，避免公网机器把状态接口暴露出去。"""
    value = (os.environ.get("SQUAD_RADIO_HEALTH_HOST") or "").strip()
    return value or "127.0.0.1"


def main() -> None:
    log_path = configure_logging(
        os.environ.get("SQUAD_RADIO_LOG_DIR") or None,
        foreground=_log_console_override(),
        max_log_mb=_log_max_mb(),
    )
    logging.getLogger(__name__).info("Squad Radio 启动，日志：%s", log_path)
    build_bot(health_port=_health_port(), health_host=_health_host()).run()


if __name__ == "__main__":
    main()
