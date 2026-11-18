"""Broadcast engine: rules, noise control and subscription feedback loop."""
from __future__ import annotations

from datetime import timedelta

from .broadcasters import Broadcaster
from .config import AppConfig, LOCAL_TZ
from .models import Broadcast, Event, EventType
from .persona import ArchitectPersona
from .rules import Rule, RuleContext
from .storage import Storage


class NoiseGovernor:
    """Keep proactive messages useful instead of noisy."""

    def __init__(self, config: AppConfig, storage: Storage):
        self.config = config
        self.storage = storage

    def allow(self, broadcast: Broadcast, event_ts) -> tuple[bool, str]:
        high = self.config.noise.high_priority_passthrough

        if self.config.noise.is_quiet(event_ts) and broadcast.priority < high:
            return False, "quiet_hours"

        last = self.storage.last_broadcast(broadcast.event_key)
        if last and event_ts - last < timedelta(
            minutes=self.config.noise.dedupe_minutes
        ):
            return False, "dedupe"

        since = event_ts - timedelta(days=1)
        if (
            self.storage.count_broadcasts(broadcast.group_id, since)
            >= self.config.noise.daily_cap
            and broadcast.priority < high
        ):
            return False, "daily_cap"

        return True, "ok"


class RadioEngine:
    def __init__(
        self,
        config: AppConfig,
        storage: Storage,
        rules: list[Rule],
        broadcaster: Broadcaster,
        persona: ArchitectPersona | None = None,
    ):
        self.config = config
        self.storage = storage
        self.rules = rules
        self.broadcaster = broadcaster
        self.persona = persona or ArchitectPersona(config.persona)
        self.governor = NoiseGovernor(config, storage)

    def seed_subscriptions(self) -> None:
        """Initialize subscriptions from config without overwriting runtime changes."""
        for group in self.config.groups:
            self.storage.seed_subscriptions(group.id, group.subscriptions)

    def process(self, event: Event) -> list[Broadcast]:
        group = self.config.group(event.group_id)
        if group and not group.enabled:
            return []

        if self.storage.is_opted_out(event.group_id, event.user_id, "all"):
            return []
        if self.storage.is_opted_out(
            event.group_id, event.user_id, self._kind_for(event)
        ):
            return []

        if event.type == EventType.PRICE_SNAPSHOT and event.value is not None:
            self.storage.record_price(event.subject, event.value, event.ts)

        ctx = RuleContext(
            storage=self.storage,
            config=self.config,
            now=event.ts.astimezone(LOCAL_TZ),
        )

        drafts: list[Broadcast] = []
        for rule in self.rules:
            drafts.extend(rule.evaluate(event, ctx))

        for draft in drafts:
            draft.text = self.persona.render(
                draft.text, self.persona.context_for_event(event, draft)
            )

        sent: list[Broadcast] = []
        for draft in sorted(drafts, key=lambda item: -item.priority):
            allowed, _reason = self.governor.allow(draft, event.ts)
            if not allowed:
                continue
            draft.created_at = event.ts
            self.broadcaster.send(draft)
            self.storage.record_broadcast(draft)
            sent.append(draft)
        return sent

    def handle_command(
        self, text: str, group_id: str | None, user_id: str | None
    ) -> str:
        """Handle a reply-style command, voiced by the Architect persona."""
        reply = self._handle_command_plain(text, group_id, user_id)
        return self.persona.render(reply, self.persona.context_for_command(text, reply))

    def _handle_command_plain(
        self, text: str, group_id: str | None, user_id: str | None
    ) -> str:
        """Handle a reply-style command from a group message."""
        if not group_id:
            return "请在群里使用指令。"

        parts = text.strip().split()
        if not parts:
            return "可用指令：订阅 / 退订 / 免打扰 / 取消免打扰"

        if any(word in text for word in ("你好", "您好", "在吗", "早安", "晚上好")):
            return "我们又相遇了呢。"

        command = parts[0]

        if command == "订阅":
            if len(parts) < 2:
                return "格式：订阅 物品 [涨幅阈值] [窗口分钟]"
            item = parts[1]
            try:
                threshold = (
                    float(parts[2])
                    if len(parts) > 2
                    else self.config.defaults.price_threshold_pct
                )
                window = (
                    int(parts[3])
                    if len(parts) > 3
                    else self.config.defaults.price_window_minutes
                )
            except ValueError:
                return "参数格式不对，示例：订阅 钛合金 15 30"

            self.storage.add_subscription(group_id, item, threshold, window)
            return f"已订阅 {item}：{window} 分钟涨幅 ≥ {threshold:g}% 时播报。"

        if command == "退订":
            if len(parts) < 2:
                return "格式：退订 物品"
            item = parts[1]
            removed = self.storage.remove_subscription(group_id, item)
            return f"已退订 {item}。" if removed else f"没有找到 {item} 的订阅。"

        if command in {"免打扰", "安静"}:
            if not user_id:
                return "需要用户 ID 才能设置免打扰。"
            self.storage.set_optout(group_id, user_id, "all", True)
            return "已开启免打扰，主动播报不再 @ 你。"

        if command in {"取消免打扰", "取消安静"}:
            if not user_id:
                return "需要用户 ID 才能取消免打扰。"
            self.storage.set_optout(group_id, user_id, "all", False)
            return "已取消免打扰。"

        if command in {"帮助", "help"}:
            return "订阅 物品 [阈值] [窗口] / 退订 物品 / 免打扰 / 取消免打扰"

        return f"未识别指令：{command}"

    @staticmethod
    def _kind_for(event: Event) -> str:
        return {
            EventType.PRICE_SNAPSHOT: "price",
            EventType.RED_DROP: "red",
            EventType.DAILY_PASSWORD: "daily",
            EventType.TASK_COMPLETED: "task",
        }[event.type]
