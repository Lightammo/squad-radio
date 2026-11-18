"""Core data models for Squad Radio."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    PRICE_SNAPSHOT = "price_snapshot"
    RED_DROP = "red_drop"
    DAILY_PASSWORD = "daily_password"
    TASK_COMPLETED = "task_completed"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Event:
    """A normalized input event from any data source."""

    type: EventType
    subject: str
    value: float | None = None
    group_id: str | None = None
    user_id: str | None = None
    ts: datetime = field(default_factory=utcnow)
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        raw_type = data.get("type")
        try:
            event_type = EventType(raw_type)
        except ValueError as exc:
            raise ValueError(f"Unknown event type: {raw_type}") from exc

        raw_ts = data.get("ts")
        if isinstance(raw_ts, str):
            ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        elif isinstance(raw_ts, (int, float)):
            ts = datetime.fromtimestamp(raw_ts, tz=timezone.utc)
        else:
            ts = utcnow()

        return cls(
            type=event_type,
            subject=str(data.get("subject", "")),
            value=float(data["value"]) if data.get("value") is not None else None,
            group_id=data.get("group_id"),
            user_id=data.get("user_id"),
            ts=ts,
            payload=dict(data.get("payload") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value,
            "subject": self.subject,
            "value": self.value,
            "group_id": self.group_id,
            "user_id": self.user_id,
            "ts": self.ts.isoformat(),
            "payload": self.payload,
        }


@dataclass
class Broadcast:
    """A message ready to be delivered to a group."""

    group_id: str
    text: str
    event_key: str = ""
    priority: int = 1
    target_user_id: str | None = None
    actions: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "text": self.text,
            "event_key": self.event_key,
            "priority": self.priority,
            "target_user_id": self.target_user_id,
            "actions": self.actions,
            "created_at": self.created_at.isoformat(),
        }
