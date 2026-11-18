"""SQLite-backed state, subscriptions and broadcast history."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .config import SubscriptionRule
from .models import Broadcast


def _iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


class Storage:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        if self.db_path.parent != Path("."):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS price_points (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item TEXT NOT NULL,
                    price REAL NOT NULL,
                    ts TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_price_item_ts
                    ON price_points(item, ts);

                CREATE TABLE IF NOT EXISTS broadcasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    event_key TEXT NOT NULL,
                    text TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    ts TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_broadcast_key_ts
                    ON broadcasts(event_key, ts);
                CREATE INDEX IF NOT EXISTS idx_broadcast_group_ts
                    ON broadcasts(group_id, ts);

                CREATE TABLE IF NOT EXISTS subscriptions (
                    group_id TEXT NOT NULL,
                    item TEXT NOT NULL,
                    threshold_pct REAL NOT NULL,
                    window_minutes INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (group_id, item)
                );

                CREATE TABLE IF NOT EXISTS optouts (
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (group_id, user_id, kind)
                );
                """
            )

    def record_price(self, item: str, price: float, ts: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO price_points(item, price, ts) VALUES (?, ?, ?)",
                (item, price, _iso(ts)),
            )

    def price_points(self, item: str, since: datetime) -> list[tuple[float, datetime]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT price, ts FROM price_points "
                "WHERE item = ? AND ts >= ? ORDER BY ts ASC",
                (item, _iso(since)),
            ).fetchall()
        return [(float(price), _parse(ts)) for price, ts in rows]

    def last_broadcast(self, event_key: str) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT ts FROM broadcasts WHERE event_key = ? ORDER BY ts DESC LIMIT 1",
                (event_key,),
            ).fetchone()
        return _parse(row[0]) if row else None

    def record_broadcast(self, broadcast: Broadcast) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO broadcasts(group_id, event_key, text, priority, ts) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    broadcast.group_id,
                    broadcast.event_key,
                    broadcast.text,
                    broadcast.priority,
                    _iso(broadcast.created_at),
                ),
            )

    def count_broadcasts(self, group_id: str, since: datetime) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM broadcasts WHERE group_id = ? AND ts >= ?",
                (group_id, _iso(since)),
            ).fetchone()
        return int(row[0]) if row else 0

    def recent_broadcasts(self, limit: int = 20) -> list[Broadcast]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT group_id, event_key, text, priority, ts "
                "FROM broadcasts ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            Broadcast(
                group_id=group_id,
                text=text,
                event_key=event_key,
                priority=priority,
                created_at=_parse(ts),
            )
            for group_id, event_key, text, priority, ts in rows
        ]

    def get_subscriptions(self, group_id: str) -> list[SubscriptionRule]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT item, threshold_pct, window_minutes, enabled "
                "FROM subscriptions WHERE group_id = ?",
                (group_id,),
            ).fetchall()
        return [
            SubscriptionRule(
                item=item,
                threshold_pct=float(threshold_pct),
                window_minutes=int(window_minutes),
                enabled=bool(enabled),
            )
            for item, threshold_pct, window_minutes, enabled in rows
        ]

    def add_subscription(
        self, group_id: str, item: str, threshold_pct: float, window_minutes: int
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO subscriptions(group_id, item, threshold_pct, window_minutes, enabled) "
                "VALUES (?, ?, ?, ?, 1) "
                "ON CONFLICT(group_id, item) DO UPDATE SET "
                "threshold_pct = excluded.threshold_pct, "
                "window_minutes = excluded.window_minutes, enabled = 1",
                (group_id, item, threshold_pct, window_minutes),
            )

    def remove_subscription(self, group_id: str, item: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM subscriptions WHERE group_id = ? AND item = ?",
                (group_id, item),
            )
        return cursor.rowcount > 0

    def set_optout(self, group_id: str, user_id: str, kind: str, enabled: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO optouts(group_id, user_id, kind, enabled) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(group_id, user_id, kind) DO UPDATE SET enabled = excluded.enabled",
                (group_id, user_id, kind, int(enabled)),
            )

    def is_opted_out(self, group_id: str | None, user_id: str | None, kind: str) -> bool:
        if not group_id or not user_id:
            return False
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT kind, enabled FROM optouts WHERE group_id = ? AND user_id = ?",
                (group_id, user_id),
            ).fetchall()
        for row_kind, enabled in rows:
            if enabled and row_kind in {"all", kind}:
                return True
        return False

    def seed_subscriptions(self, group_id: str, rules: Iterable[SubscriptionRule]) -> None:
        for rule in rules:
            if not rule.enabled:
                continue
            existing = self.get_subscriptions(group_id)
            if any(item.item == rule.item for item in existing):
                continue
            self.add_subscription(
                group_id, rule.item, rule.threshold_pct, rule.window_minutes
            )
