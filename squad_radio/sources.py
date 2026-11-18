"""Data source adapters. All sources emit normalized Event objects."""
from __future__ import annotations

import json
import urllib.request
from abc import ABC, abstractmethod
from datetime import timedelta
from pathlib import Path
from typing import Any

from .models import Event, EventType, utcnow


class DataSource(ABC):
    @abstractmethod
    def poll(self) -> list[Event]:
        """Return events gathered since the last poll."""


class MockSource(DataSource):
    """In-memory source for demos and tests."""

    def __init__(self, events: list[Event] | None = None):
        self._queue: list[Event] = list(events or [])

    def feed(self, event: Event) -> None:
        self._queue.append(event)

    def poll(self) -> list[Event]:
        events = self._queue
        self._queue = []
        return events

    @classmethod
    def demo(cls) -> "MockSource":
        now = utcnow()
        return cls(
            [
                Event(
                    type=EventType.PRICE_SNAPSHOT,
                    subject="钛合金",
                    value=6.95,
                    group_id="demo-group",
                    ts=now - timedelta(minutes=25),
                ),
                Event(
                    type=EventType.PRICE_SNAPSHOT,
                    subject="钛合金",
                    value=8.2,
                    group_id="demo-group",
                    ts=now - timedelta(seconds=10),
                ),
                Event(
                    type=EventType.RED_DROP,
                    subject="曼德尔超算单元",
                    value=280,
                    group_id="demo-group",
                    user_id="10001",
                    ts=now,
                    payload={"map": "长弓溪谷"},
                ),
                Event(
                    type=EventType.TASK_COMPLETED,
                    subject="特勤处制造",
                    group_id="demo-group",
                    user_id="10002",
                    ts=now,
                    payload={"machine": "制造台"},
                ),
                Event(
                    type=EventType.DAILY_PASSWORD,
                    subject=now.astimezone().strftime("%Y-%m-%d"),
                    group_id="demo-group",
                    ts=now,
                    payload={"password": "DF-1118"},
                ),
            ]
        )


class JsonlSource(DataSource):
    """Read newline-delimited JSON events from a file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._offset = 0

    def poll(self) -> list[Event]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        new_lines = lines[self._offset :]
        self._offset = len(lines)

        events: list[Event] = []
        for line in new_lines:
            line = line.strip()
            if not line:
                continue
            try:
                data: Any = json.loads(line)
                if isinstance(data, dict):
                    events.append(Event.from_dict(data))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
        return events


class DeltaForceHttpSource(DataSource):
    """Minimal HTTP price adapter for data providers such as 数据帝开放平台.

    The response is expected to be a list of objects with ``name`` and ``price``,
    or a dict containing an ``items`` / ``data`` list with that shape.
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        path: str = "/price/all",
        timeout: int = 10,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.path = path
        self.timeout = timeout

    def poll(self) -> list[Event]:
        url = f"{self.base_url}{self.path}"
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers, method="GET")

        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.load(response)

        if isinstance(payload, dict):
            items = payload.get("items") or payload.get("data") or []
        elif isinstance(payload, list):
            items = payload
        else:
            items = []

        now = utcnow()
        events: list[Event] = []
        for row in items:
            if not isinstance(row, dict):
                continue
            name = row.get("name") or row.get("item")
            price = row.get("price")
            if not name or price is None:
                continue
            try:
                value = float(price)
            except (TypeError, ValueError):
                continue
            events.append(
                Event(
                    type=EventType.PRICE_SNAPSHOT,
                    subject=str(name),
                    value=value,
                    ts=now,
                    payload={"source": "http"},
                )
            )
        return events
