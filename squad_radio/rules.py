"""Trigger rules: decide whether an event deserves a group broadcast."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import AppConfig, LOCAL_TZ, SubscriptionRule
from .models import Broadcast, Event, EventType
from .storage import Storage


@dataclass
class RuleContext:
    storage: Storage
    config: AppConfig
    now: datetime | None = None


class Rule(ABC):
    name: str = "base"

    @abstractmethod
    def evaluate(self, event: Event, ctx: RuleContext) -> list[Broadcast]:
        raise NotImplementedError


def _pick(variants: list[str], key: str) -> str:
    """Stable variant selection so the same event keeps the same wording."""
    return variants[sum(ord(char) for char in key) % len(variants)]


class PriceSpikeRule(Rule):
    name = "price_spike"

    def evaluate(self, event: Event, ctx: RuleContext) -> list[Broadcast]:
        if (
            event.type != EventType.PRICE_SNAPSHOT
            or event.value is None
            or not event.group_id
        ):
            return []

        rules = ctx.storage.get_subscriptions(event.group_id)
        if not rules:
            rules = [
                SubscriptionRule(
                    item=event.subject,
                    threshold_pct=ctx.config.defaults.price_threshold_pct,
                    window_minutes=ctx.config.defaults.price_window_minutes,
                )
            ]
        matched = [
            rule
            for rule in rules
            if rule.enabled and rule.item == event.subject
        ]
        if not matched:
            return []

        drafts: list[Broadcast] = []
        for rule in matched:
            since = event.ts - timedelta(minutes=rule.window_minutes)
            points = ctx.storage.price_points(event.subject, since)
            if len(points) < 2:
                continue

            old_price = points[0][0]
            new_price = points[-1][0]
            if old_price <= 0:
                continue

            pct = (new_price - old_price) / old_price * 100
            if pct < rule.threshold_pct:
                continue

            bucket = int(event.ts.timestamp() // 600)
            event_key = f"price:{event.subject}:{bucket}"
            text = _pick(
                [
                    "{item} 近{minutes}分钟涨了 {pct:.0f}%，当前 {price:g} 万。想出手的现在看一眼，别等它又跌回去。",
                    "行情喊话：{item} {minutes}分钟涨幅 {pct:.0f}%，现价 {price:g} 万。这波要不要跟，群里说了算。",
                    "{item} 涨了 {pct:.0f}%，{price:g} 万。价格来找你了，记得看一眼再决定。",
                ],
                event_key,
            ).format(
                item=event.subject,
                pct=pct,
                price=new_price,
                minutes=rule.window_minutes,
            )
            drafts.append(
                Broadcast(
                    group_id=event.group_id,
                    text=text,
                    event_key=event_key,
                    priority=2,
                    actions=[f"订阅 {event.subject}"],
                )
            )
        return drafts


class RedDropRule(Rule):
    name = "red_drop"

    def evaluate(self, event: Event, ctx: RuleContext) -> list[Broadcast]:
        if event.type != EventType.RED_DROP or not event.group_id:
            return []

        value = event.value or 0
        if value < ctx.config.defaults.red_min_value_wan:
            return []

        user = event.user_id or "一位鼠鼠"
        map_name = event.payload.get("map") or "某个角落"
        event_key = f"red:{user}:{event.subject}:{int(event.ts.timestamp() // 60)}"
        text = _pick(
            [
                "@{user} 在{map}摸到了{item}，估值 {value:g} 万。群里先安静三秒，恭喜就完事了。",
                "大红播报：@{user} 在{map}掏出{item}，估值 {value:g} 万。这波属于公共事件了。",
                "@{user} 的{map}之旅不太一样——{item} 到手，估值 {value:g} 万。羡慕可以，别抢。",
            ],
            event_key,
        ).format(user=user, map=map_name, item=event.subject, value=value)

        return [
            Broadcast(
                group_id=event.group_id,
                text=text,
                event_key=event_key,
                priority=3,
                target_user_id=event.user_id,
                actions=["订阅 大红播报"],
            )
        ]


class DailyPasswordRule(Rule):
    name = "daily_password"

    def evaluate(self, event: Event, ctx: RuleContext) -> list[Broadcast]:
        if event.type != EventType.DAILY_PASSWORD or not event.group_id:
            return []

        password = event.payload.get("password") or event.subject
        day = event.ts.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")
        event_key = f"password:{day}"
        text = _pick(
            [
                "今日作战密码：{password}。今天该干什么，群里这条就够了。",
                "早八播报：密码 {password} 已就位，出门前看一眼。",
            ],
            event_key,
        ).format(password=password)

        return [
            Broadcast(
                group_id=event.group_id,
                text=text,
                event_key=event_key,
                priority=1,
                actions=["订阅 每日简报"],
            )
        ]


class TaskCompletedRule(Rule):
    name = "task_completed"

    def evaluate(self, event: Event, ctx: RuleContext) -> list[Broadcast]:
        if event.type != EventType.TASK_COMPLETED or not event.group_id:
            return []

        user = event.user_id or "一位鼠鼠"
        machine = event.payload.get("machine") or event.subject
        day = event.ts.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")
        event_key = f"task:{user}:{machine}:{day}"
        text = _pick(
            [
                "@{user} 的{machine}完成了，记得去收，不然产能白给。",
                "收菜提醒：@{user} 的{machine}已经好了，别让特勤处白干活。",
            ],
            event_key,
        ).format(user=user, machine=machine)

        return [
            Broadcast(
                group_id=event.group_id,
                text=text,
                event_key=event_key,
                priority=2,
                target_user_id=event.user_id,
            )
        ]


def default_rules() -> list[Rule]:
    return [
        PriceSpikeRule(),
        RedDropRule(),
        DailyPasswordRule(),
        TaskCompletedRule(),
    ]
