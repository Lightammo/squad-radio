"""Hourly manufacture recommendation scheduler for the always-on cloud bot.

Runs as a daemon thread inside ``main.py`` so the existing supervisor / health
check / graceful shutdown keeps working.  A tiny state file prevents duplicate
sends when the process is restarted inside the same hour.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import LOCAL_TZ
from .kook import KookClient
from .manufacture import (
    DEFAULT_URL,
    fetch_manufacture_recommendations,
    format_manufacture_broadcast,
)

LOG = logging.getLogger("squad_radio.manufacture_bot")


class ManufactureScheduler:
    def __init__(
        self,
        client: KookClient,
        channel_id: str,
        *,
        state_path: Path,
        level: int = 3,
        rank_type: str = "hour",
        top: int = 1,
        minute: int = 5,
        url: str = DEFAULT_URL,
    ):
        self.client = client
        self.channel_id = channel_id
        self.state_path = state_path
        self.level = level
        self.rank_type = rank_type
        self.top = top
        self.minute = minute
        self.url = url
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hour(self) -> str:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return str(data.get("last_hour", ""))
        except (OSError, ValueError, TypeError):
            return ""

    def _mark_sent(self, hour_key: str) -> None:
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"last_hour": hour_key}, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self.state_path)

    def send_hourly(self, hour_key: str) -> bool:
        """Fetch, format and send one hourly report. Returns True when sent."""
        if self._last_hour() == hour_key:
            LOG.info("制造推荐 %s 已播报过，跳过", hour_key)
            return False

        update, recommendations = fetch_manufacture_recommendations(
            level=self.level,
            rank_type=self.rank_type,
            top_per_department=self.top,
            url=self.url,
        )
        content = format_manufacture_broadcast(
            update,
            recommendations,
            level=self.level,
            rank_type=self.rank_type,
        )
        nonce = f"manufacture:{hour_key}:{self.level}:{self.rank_type}:{self.top}"
        self.client.send_message(self.channel_id, content, msg_type=9, nonce=nonce)
        self._mark_sent(hour_key)
        LOG.info(
            "制造推荐已播报：频道 %s，小时 %s，条目 %d，数据更新 %s",
            self.channel_id,
            hour_key,
            len(recommendations),
            update,
        )
        return True

    def run(self, stop_event: threading.Event | None = None) -> None:
        while stop_event is None or not stop_event.is_set():
            now = datetime.now(LOCAL_TZ)
            hour_key = now.strftime("%Y-%m-%dT%H")
            sent = False
            try:
                sent = self.send_hourly(hour_key)
            except Exception:
                LOG.exception("制造推荐小时播报失败，将在下一个重试点再试")

            target = now.replace(minute=self.minute, second=0, microsecond=0)
            if sent or target <= now:
                target += timedelta(hours=1)
            delay = max(30.0, (target - now).total_seconds())
            LOG.info("下次制造推荐检查：%s（%.0f 秒后）", target.isoformat(), delay)
            if stop_event is not None:
                stop_event.wait(delay)
            else:
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


def build_scheduler_from_env(
    token: str,
    root: Path,
    *,
    client: KookClient | None = None,
) -> ManufactureScheduler | None:
    """Return a configured scheduler, or None when the feature is disabled."""
    channel = os.environ.get("SQUAD_RADIO_MANUFACTURE_CHANNEL", "").strip()
    if not channel:
        return None
    return ManufactureScheduler(
        client or KookClient(token),
        channel,
        state_path=root / "data" / "manufacture_state.json",
        level=_env_int("SQUAD_RADIO_MANUFACTURE_LEVEL", 3),
        rank_type=os.environ.get("SQUAD_RADIO_MANUFACTURE_RANK", "hour").strip() or "hour",
        top=_env_int("SQUAD_RADIO_MANUFACTURE_TOP", 1),
        minute=min(59, max(0, _env_int("SQUAD_RADIO_MANUFACTURE_MINUTE", 5))),
        url=os.environ.get("SQUAD_RADIO_MANUFACTURE_URL", "").strip() or DEFAULT_URL,
    )


def start_scheduler_from_env(token: str, root: Path) -> ManufactureScheduler | None:
    scheduler = build_scheduler_from_env(token, root)
    if scheduler is None:
        return None
    thread = threading.Thread(
        target=scheduler.run,
        name="manufacture-scheduler",
        daemon=True,
    )
    thread.start()
    LOG.info(
        "制造推荐小时播报已启动：频道 %s，等级 %d，排序 %s，每榜 Top%d",
        scheduler.channel_id,
        scheduler.level,
        scheduler.rank_type,
        scheduler.top,
    )
    return scheduler
