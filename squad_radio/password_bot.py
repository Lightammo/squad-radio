"""Daily 00:00 password broadcast scheduler for the always-on cloud bot.

Runs as a daemon thread inside ``main.py`` so the existing supervisor / health
check / graceful shutdown keeps working. A tiny state file keyed by local date
prevents duplicate sends when the process restarts on the same day, and a KOOK
nonce adds a second layer of server-side dedupe.

Cross-midnight the upstream source may not have refreshed yet. The scheduler
keeps retrying within a short window after the target time and never sends
stale/yesterday codes as today's password.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import LOCAL_TZ
from .daily_broadcast import build_broadcast
from .kook import KookApiError, KookClient
from .password import PasswordCache

LOG = logging.getLogger("squad_radio.password_bot")


class PasswordScheduler:
    def __init__(
        self,
        client: KookClient,
        channel_id: str,
        cache: PasswordCache,
        *,
        state_path: Path,
        hour: int = 0,
        minute: int = 0,
        retry_minutes: int = 30,
        retry_interval: int = 60,
    ):
        self.client = client
        self.channel_id = channel_id
        self.cache = cache
        self.state_path = state_path
        self.hour = hour
        self.minute = minute
        self.retry_minutes = retry_minutes
        self.retry_interval = retry_interval
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def _state(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _last_date(self) -> str:
        return str(self._state().get("last_date", ""))

    def _mark_sent(self, date_key: str, msg_id: str) -> None:
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {"last_date": date_key, "last_msg_id": msg_id},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        tmp.replace(self.state_path)

    def send_daily(self, date_key: str) -> bool:
        """Fetch today's password and broadcast once. Returns True when sent."""
        if self._last_date() == date_key:
            LOG.info("今日密码 %s 已播报过，跳过", date_key)
            return False

        data = self.cache.get()
        if data is None or data.date != date_key:
            LOG.warning("今日密码 %s 还没更新，稍后重试", date_key)
            return False

        content = build_broadcast(data)
        nonce = f"daily-password:{date_key}"
        result = self.client.send_message(
            self.channel_id, content, msg_type=9, nonce=nonce
        )
        self._mark_sent(date_key, str((result or {}).get("msg_id", "")))
        LOG.info("今日密码已播报：频道 %s，日期 %s", self.channel_id, date_key)
        return True

    def _next_target(self, now: datetime) -> datetime:
        return now.replace(
            hour=self.hour, minute=self.minute, second=0, microsecond=0
        )

    def run(self, stop_event: threading.Event | None = None) -> None:
        while stop_event is None or not stop_event.is_set():
            now = datetime.now(LOCAL_TZ)
            date_key = now.date().isoformat()
            target = self._next_target(now)
            already_sent = self._last_date() == date_key
            sent = False

            if not already_sent and now >= target:
                if now < target + timedelta(minutes=self.retry_minutes):
                    try:
                        sent = self.send_daily(date_key)
                    except KookApiError as exc:
                        LOG.error(
                            "今日密码播报失败：code=%s message=%s", exc.code, exc.message
                        )
                    except Exception:
                        LOG.exception("今日密码播报失败，将在重试窗口内再试")
                else:
                    LOG.warning(
                        "今日密码 %s 超过重试窗口仍未拿到，今天不再尝试", date_key
                    )

            # 决定下次唤醒时间：已发/放弃 -> 明天目标点；窗口内失败 -> 间隔重试；否则 -> 今天目标点
            if sent or already_sent or now >= target + timedelta(minutes=self.retry_minutes):
                target = (now + timedelta(days=1)).replace(
                    hour=self.hour, minute=self.minute, second=0, microsecond=0
                )
            elif now >= target:
                target = now + timedelta(seconds=self.retry_interval)

            delay = max(15.0, (target - now).total_seconds())
            LOG.info("下次今日密码播报检查：%s（%.0f 秒后）", target.isoformat(), delay)
            if stop_event is not None:
                stop_event.wait(delay)
            else:
                import time

                time.sleep(delay)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value


def _enabled_channel() -> str:
    channel = os.environ.get("SQUAD_RADIO_PASSWORD_CHANNEL", "").strip()
    if channel in ("off", "0"):
        return ""
    return channel


def build_scheduler_from_env(
    token: str,
    root: Path,
    *,
    client: KookClient | None = None,
) -> PasswordScheduler | None:
    """Return a configured scheduler, or None when the feature is disabled."""
    channel = _enabled_channel()
    if not channel:
        return None
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return PasswordScheduler(
        client or KookClient(token),
        channel,
        PasswordCache(data_dir / "password_cache.json"),
        state_path=data_dir / "password_daily_state.json",
        hour=min(23, max(0, _env_int("SQUAD_RADIO_PASSWORD_HOUR", 0))),
        minute=min(59, max(0, _env_int("SQUAD_RADIO_PASSWORD_MINUTE", 0))),
        retry_minutes=max(1, _env_int("SQUAD_RADIO_PASSWORD_RETRY_MINUTES", 30)),
        retry_interval=max(15, _env_int("SQUAD_RADIO_PASSWORD_RETRY_INTERVAL", 60)),
    )


def start_scheduler_from_env(
    token: str, root: Path
) -> PasswordScheduler | None:
    scheduler = build_scheduler_from_env(token, root)
    if scheduler is None:
        return None
    thread = threading.Thread(
        target=scheduler.run,
        name="password-daily-scheduler",
        daemon=True,
    )
    thread.start()
    LOG.info(
        "今日密码零点播报已启动：频道 %s，目标 %02d:%02d，重试窗口 %d 分钟",
        scheduler.channel_id,
        scheduler.hour,
        scheduler.minute,
        scheduler.retry_minutes,
    )
    return scheduler
