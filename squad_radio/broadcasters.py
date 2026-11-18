"""Output adapters: console, webhook, or a combination."""
from __future__ import annotations

import json
import urllib.request
from abc import ABC, abstractmethod

from .models import Broadcast


class Broadcaster(ABC):
    @abstractmethod
    def send(self, broadcast: Broadcast) -> None:
        raise NotImplementedError


class ConsoleBroadcaster(Broadcaster):
    def send(self, broadcast: Broadcast) -> None:
        local = broadcast.created_at.astimezone()
        timestamp = local.strftime("%H:%M:%S")
        suffix = f"  动作：{' / '.join(broadcast.actions)}" if broadcast.actions else ""
        print(
            f"[{timestamp}] 群 {broadcast.group_id} | P{broadcast.priority} | "
            f"{broadcast.text}{suffix}"
        )


class WebhookBroadcaster(Broadcaster):
    """POST broadcasts to an HTTP gateway that forwards to QQ/KOOK."""

    def __init__(self, url: str, timeout: int = 10):
        self.url = url
        self.timeout = timeout

    def send(self, broadcast: Broadcast) -> None:
        payload = json.dumps(broadcast.to_dict(), ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            response.read()


class CompositeBroadcaster(Broadcaster):
    def __init__(self, broadcasters: list[Broadcaster]):
        self.broadcasters = broadcasters

    def send(self, broadcast: Broadcast) -> None:
        for broadcaster in self.broadcasters:
            broadcaster.send(broadcast)
