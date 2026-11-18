"""Command line entry point for Squad Radio."""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

from .broadcasters import CompositeBroadcaster, ConsoleBroadcaster, WebhookBroadcaster
from .config import AppConfig, load_config
from .engine import RadioEngine
from .kook import KookApiError, KookClient
from .kook_bot import KookBot
from .password import PasswordCache
from .rules import default_rules
from .sources import JsonlSource, MockSource
from .storage import Storage


def build_engine(
    config_path: str | None = None, webhook_url: str | None = None
) -> tuple[AppConfig, Storage, RadioEngine]:
    config = load_config(config_path)
    broadcasters = [ConsoleBroadcaster()]
    if webhook_url:
        broadcasters.append(WebhookBroadcaster(webhook_url))
    storage = Storage(config.db_path)
    engine = RadioEngine(
        config=config,
        storage=storage,
        rules=default_rules(),
        broadcaster=CompositeBroadcaster(broadcasters),
    )
    engine.seed_subscriptions()
    return config, storage, engine


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="Path to config.toml")
    parser.add_argument("--webhook", help="HTTP webhook URL for QQ/KOOK gateway")
    parser.add_argument(
        "--token-file",
        help="Read KOOK token from a file (safer than env vars in Git Bash)",
    )


def _kook_token(args: argparse.Namespace) -> str:
    token = None
    token_file = getattr(args, "token_file", None)
    if token_file:
        token = Path(token_file).read_text(encoding="utf-8").strip()
    else:
        token = os.environ.get("KOOK_TOKEN")
    if not token:
        raise SystemExit("请设置环境变量 KOOK_TOKEN 或用 --token-file 指定 Token 文件（不要提交到仓库）")
    if ":/" in token or "\\" in token or " " in token:
        raise SystemExit(
            "Token 内容异常：Git Bash 会把 token 里的 /xxx 当成路径改写。"
            "请在命令前加 MSYS_NO_PATHCONV=1，或把 token 写入文件后用 --token-file 传入。"
        )
    return token


def _kook_client(args: argparse.Namespace) -> KookClient:
    return KookClient(_kook_token(args))


def main() -> None:
    parser = argparse.ArgumentParser(prog="squad-radio")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-db", help="Initialize SQLite database")
    _add_common(init_parser)

    demo_parser = subparsers.add_parser("demo", help="Run a scripted demo")
    _add_common(demo_parser)

    ingest_parser = subparsers.add_parser("ingest-jsonl", help="Ingest JSONL events once")
    ingest_parser.add_argument("--path", required=True, help="Path to events.jsonl")
    _add_common(ingest_parser)

    command_parser = subparsers.add_parser("command", help="Run a group command")
    command_parser.add_argument("--group", required=True)
    command_parser.add_argument("--user", required=True)
    command_parser.add_argument("--text", required=True)
    _add_common(command_parser)

    status_parser = subparsers.add_parser("status", help="Show local state")
    _add_common(status_parser)

    gateway_parser = subparsers.add_parser("kook-gateway", help="Get KOOK WebSocket gateway")
    _add_common(gateway_parser)

    channels_parser = subparsers.add_parser("kook-channels", help="List KOOK text channels")
    channels_parser.add_argument("--guild", required=True)
    _add_common(channels_parser)

    channel_view_parser = subparsers.add_parser("kook-channel-view", help="Inspect a KOOK channel")
    channel_view_parser.add_argument("--channel", required=True)
    _add_common(channel_view_parser)

    send_parser = subparsers.add_parser("kook-send", help="Send a KOOK channel message")
    send_parser.add_argument("--channel", required=True)
    send_parser.add_argument("--text", required=True)
    send_parser.add_argument("--type", type=int, default=9)
    _add_common(send_parser)

    bot_parser = subparsers.add_parser("kook-bot", help="Run the always-on password listener")
    bot_parser.add_argument("--password-cache", default="data/password_cache.json")
    bot_parser.add_argument("--state-file", default="data/kook_bot_state.json")
    bot_parser.add_argument("--trigger", default="今日密码")
    _add_common(bot_parser)

    args = parser.parse_args()

    if args.command == "kook-bot":
        token = _kook_token(args)
        cache = PasswordCache(args.password_cache)
        bot = KookBot(
            token,
            password_cache=cache,
            state_path=args.state_file,
            trigger=args.trigger,
        )
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        )
        bot.run()
        return

    if args.command.startswith("kook-"):
        client = _kook_client(args)
        try:
            if args.command == "kook-gateway":
                print(json.dumps(client.gateway(), ensure_ascii=False, indent=2))
            elif args.command == "kook-channels":
                for channel in client.channels(args.guild):
                    print(
                        f"{channel.get('id')}\t{channel.get('name')}\ttype={channel.get('type')}"
                    )
            elif args.command == "kook-channel-view":
                print(json.dumps(client.view_channel(args.channel), ensure_ascii=False, indent=2))
            elif args.command == "kook-send":
                result = client.send_message(args.channel, args.text, msg_type=args.type)
                print(json.dumps(result, ensure_ascii=False))
        except KookApiError as exc:
            print(f"KOOK 调用失败：code={exc.code} http={exc.http_status} message={exc.message}")
            raise SystemExit(1) from exc
        return

    config, storage, engine = build_engine(args.config, getattr(args, "webhook", None))

    if args.command == "init-db":
        print(f"数据库已就绪：{Path(config.db_path).resolve()}")
        return

    if args.command == "demo":
        config.noise.quiet_hours = []
        config.noise.daily_cap = 99
        print("Squad Radio demo：注入示例事件")
        for event in MockSource.demo().poll():
            print(f"→ 输入 {event.type.value}: {event.subject}")
            engine.process(event)
        print("Demo 完成")
        return

    if args.command == "ingest-jsonl":
        events = JsonlSource(args.path).poll()
        print(f"读取到 {len(events)} 条事件")
        for event in events:
            engine.process(event)
        return

    if args.command == "command":
        reply = engine.handle_command(args.text, args.group, args.user)
        print(reply)
        return

    if args.command == "status":
        print(f"数据库：{Path(config.db_path).resolve()}")
        for group in config.groups:
            subscriptions = storage.get_subscriptions(group.id)
            print(f"群 {group.id}：{len(subscriptions)} 个订阅")
            for rule in subscriptions:
                print(
                    f"  - {rule.item}: {rule.threshold_pct:g}% / {rule.window_minutes}分钟"
                )
        recent = storage.recent_broadcasts(10)
        print(f"最近播报 {len(recent)} 条：")
        for broadcast in recent:
            print(f"  [{broadcast.created_at.isoformat()}] {broadcast.text}")


if __name__ == "__main__":
    main()
