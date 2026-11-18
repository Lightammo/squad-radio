"""Configuration loading and China-local time helpers."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LOCAL_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")


def local_now() -> datetime:
    return datetime.now(LOCAL_TZ)


@dataclass
class SubscriptionRule:
    item: str
    threshold_pct: float = 15.0
    window_minutes: int = 30
    enabled: bool = True


@dataclass
class GroupConfig:
    id: str
    name: str = ""
    enabled: bool = True
    subscriptions: list[SubscriptionRule] = field(default_factory=list)


@dataclass
class NoiseConfig:
    daily_cap: int = 12
    dedupe_minutes: int = 30
    quiet_hours: list[str] = field(default_factory=lambda: ["01:00-07:30"])
    high_priority_passthrough: int = 3

    def is_quiet(self, dt: datetime) -> bool:
        local = dt.astimezone(LOCAL_TZ)
        current = local.hour * 60 + local.minute
        for window in self.quiet_hours:
            try:
                start_text, end_text = window.split("-", 1)
                start = _minutes(start_text.strip())
                end = _minutes(end_text.strip())
            except (ValueError, AttributeError):
                continue
            if start <= end:
                if start <= current < end:
                    return True
            elif current >= start or current < end:
                return True
        return False


@dataclass
class PersonaConfig:
    enabled: bool = True
    style: str = "architect"
    intensity: str = "normal"
    address: str = "指挥官"


@dataclass
class DefaultsConfig:
    price_threshold_pct: float = 15.0
    price_window_minutes: int = 30
    red_min_value_wan: float = 100.0


@dataclass
class AppConfig:
    db_path: str = "data/squad_radio.db"
    timezone: str = "Asia/Shanghai"
    noise: NoiseConfig = field(default_factory=NoiseConfig)
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    persona: PersonaConfig = field(default_factory=PersonaConfig)
    groups: list[GroupConfig] = field(
        default_factory=lambda: [GroupConfig(id="demo-group", name="默认群")]
    )

    def group(self, group_id: str | None) -> GroupConfig | None:
        if not group_id:
            return None
        for item in self.groups:
            if item.id == group_id:
                return item
        return None


def _minutes(text: str) -> int:
    hour, minute = text.split(":", 1)
    return int(hour) * 60 + int(minute)


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load TOML config. Missing file yields a usable demo config."""
    data: dict[str, Any] = {}
    if path:
        config_path = Path(path)
        if config_path.exists():
            with config_path.open("rb") as handle:
                data = tomllib.load(handle)

    app_data = data.get("app", {})
    noise_data = data.get("noise", {})
    defaults_data = data.get("defaults", {})
    persona_data = data.get("persona", {})

    groups_data = data.get("groups", [])
    groups: list[GroupConfig] = []
    for raw_group in groups_data:
        subscriptions = [
            SubscriptionRule(
                item=str(raw.get("item", "")),
                threshold_pct=float(
                    raw.get("threshold_pct", defaults_data.get("price_threshold_pct", 15.0))
                ),
                window_minutes=int(
                    raw.get("window_minutes", defaults_data.get("price_window_minutes", 30))
                ),
                enabled=bool(raw.get("enabled", True)),
            )
            for raw in raw_group.get("subscriptions", [])
            if raw.get("item")
        ]
        groups.append(
            GroupConfig(
                id=str(raw_group.get("id", "demo-group")),
                name=str(raw_group.get("name", "")),
                enabled=bool(raw_group.get("enabled", True)),
                subscriptions=subscriptions,
            )
        )

    if not groups:
        groups = [GroupConfig(id="demo-group", name="默认群")]

    raw_db_path = str(app_data.get("db_path", "data/squad_radio.db"))
    db_path = Path(raw_db_path)
    if not db_path.is_absolute():
        base = Path(path).resolve().parent if path else Path(__file__).resolve().parent.parent
        db_path = base / db_path

    return AppConfig(
        db_path=str(db_path),
        timezone=str(app_data.get("timezone", "Asia/Shanghai")),
        noise=NoiseConfig(
            daily_cap=int(noise_data.get("daily_cap", 12)),
            dedupe_minutes=int(noise_data.get("dedupe_minutes", 30)),
            quiet_hours=list(noise_data.get("quiet_hours", ["01:00-07:30"])),
            high_priority_passthrough=int(
                noise_data.get("high_priority_passthrough", 3)
            ),
        ),
        defaults=DefaultsConfig(
            price_threshold_pct=float(defaults_data.get("price_threshold_pct", 15.0)),
            price_window_minutes=int(defaults_data.get("price_window_minutes", 30)),
            red_min_value_wan=float(defaults_data.get("red_min_value_wan", 100.0)),
        ),
        persona=PersonaConfig(
            enabled=bool(persona_data.get("enabled", True)),
            style=str(persona_data.get("style", "architect")),
            intensity=str(persona_data.get("intensity", "normal"))
            if str(persona_data.get("intensity", "normal")) in {"off", "light", "normal", "full"}
            else "normal",
            address=str(persona_data.get("address", "指挥官")),
        ),
        groups=groups,
    )
