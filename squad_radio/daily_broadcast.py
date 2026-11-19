"""每天 0 点向指定 KOOK 频道播报当日作战密码。

由定时任务在 00:00 触发。跨零点主源可能还没更新，脚本会在有限时间窗内
反复强制刷新，拿到当日密码后以 KMarkdown 卡片发送，并用 nonce 去重，
避免同一天重复播报；拿不到时绝不拿旧密码冒充。

用法：
    python -m squad_radio.daily_broadcast \
        --channel 2352172414970176 \
        --token-file .env.token \
        --max-retry-minutes 8
    # 仅预览不发送：
    python -m squad_radio.daily_broadcast --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import LOCAL_TZ, PersonaConfig
from .kook import KookApiError, KookClient
from .password import PasswordCache, PasswordData
from .persona import ArchitectPersona, PersonaContext, Tone
from .rich import format_password_card, format_password_table

LOG = logging.getLogger("squad_radio.daily_broadcast")

DEFAULT_CHANNEL = "2352172414970176"
DEFAULT_TOKEN_FILE = ".env.token"
DEFAULT_PASSWORD_CACHE = "data/password_cache.json"


def read_token(path: str | Path) -> str:
    token = Path(path).read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit(f"Token 文件为空：{path}")
    return token


def build_broadcast(data: PasswordData, persona: ArchitectPersona | None = None) -> str:
    """把当日密码渲染成定时播报卡片（不带 @ 提及，面向整个频道）。

    脚注与实时回复链路一样经过人格层，保证两条链路文案一致。
    """
    table = format_password_table(data.entries)
    if not table:
        raise ValueError("当日密码缺少六图数据，拒绝播报")
    persona = persona or ArchitectPersona(PersonaConfig())
    note = persona.render(
        "数据每天早上更新，以游戏内为准哦。",
        PersonaContext(tone=Tone.INFO, key="daily-broadcast", event_type=None),
    )
    return format_password_card(
        [table],
        title=f"今日作战密码 · {data.date}",
        mention=None,
        footnote=note,
    )


def fetch_today(
    cache: PasswordCache,
    *,
    max_retry_minutes: int,
    retry_interval: int,
) -> PasswordData | None:
    """限时反复强制刷新，直到拿到当日日期的密码；失败返回 None。"""
    deadline = time.monotonic() + max(0, max_retry_minutes) * 60
    attempt = 0
    while True:
        attempt += 1
        today = datetime.now(LOCAL_TZ).date().isoformat()
        # refresh(today) 会强制抓取；跨零点时昨天的缓存不会冒充今日数据。
        data = cache.refresh(today)
        if data and data.date == today:
            LOG.info("第 %d 次尝试拿到当日密码（date=%s, stale=%s）", attempt, data.date, data.stale)
            return data
        if time.monotonic() >= deadline:
            LOG.error("在 %d 分钟内未拿到 %s 的当日密码，放弃播报", max_retry_minutes, today)
            return None
        LOG.warning("第 %d 次未拿到当日密码，%d 秒后重试", attempt, retry_interval)
        time.sleep(retry_interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="daily-broadcast")
    parser.add_argument("--channel", default=DEFAULT_CHANNEL, help="目标文字频道 ID")
    parser.add_argument("--token-file", default=DEFAULT_TOKEN_FILE, help="KOOK token 文件")
    parser.add_argument("--password-cache", default=DEFAULT_PASSWORD_CACHE, help="密码缓存文件")
    parser.add_argument("--max-retry-minutes", type=int, default=8, help="跨零点等待当日数据的最大分钟数")
    parser.add_argument("--retry-interval", type=int, default=30, help="重试间隔秒数")
    parser.add_argument("--dry-run", action="store_true", help="只打印播报内容，不发送")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cache = PasswordCache(args.password_cache)
    data = fetch_today(
        cache,
        max_retry_minutes=args.max_retry_minutes,
        retry_interval=args.retry_interval,
    )
    if data is None:
        print("今日密码尚未更新，本次未播报。", file=sys.stderr)
        return 1

    content = build_broadcast(data)
    if args.dry_run:
        print(content)
        return 0

    token = read_token(args.token_file)
    client = KookClient(token)
    nonce = f"daily-password:{data.date}"
    try:
        result = client.send_message(args.channel, content, msg_type=9, nonce=nonce)
    except KookApiError as exc:
        LOG.error("播报发送失败：code=%s message=%s", exc.code, exc.message)
        print(f"播报发送失败：code={exc.code} message={exc.message}", file=sys.stderr)
        return 1
    msg_id = (result or {}).get("msg_id", "")
    print(f"已在频道 {args.channel} 播报今日密码（date={data.date}, msg_id={msg_id}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
