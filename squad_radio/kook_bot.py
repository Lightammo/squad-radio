"""Always-on KOOK listener for Squad Radio.

It listens on the WebSocket for group messages, and replies immediately when
someone says the trigger phrase (default: 今日密码). Replies are sent through
the REST API as KMarkdown so the asker is properly mentioned with (met).
"""
from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import websocket

from .config import LOCAL_TZ, PersonaConfig
from .kook import KookApiError, KookClient
from .password import PasswordCache, PasswordData
from .persona import ArchitectPersona, PersonaContext, Tone

LOG = logging.getLogger("squad_radio.kook_bot")


def should_reply(event: dict[str, Any], bot_user_id: str | None, trigger: str) -> bool:
    """Pure predicate so the trigger rule can be unit tested offline."""
    if int(event.get("type", -1)) not in (1, 9):
        return False
    if not event.get("target_id") or not event.get("content"):
        return False
    author_id = str(event.get("author_id") or "")
    if not author_id or author_id == "1":
        return False
    if bot_user_id and author_id == str(bot_user_id):
        return False
    extra = event.get("extra") or {}
    if isinstance(extra, dict) and (extra.get("author") or {}).get("bot"):
        return False
    return trigger in str(event["content"])


def build_reply(data: PasswordData | None, author_id: str, persona: ArchitectPersona) -> str:
    mention = f"(met){author_id}(met)"
    if data is None:
        core = f"{mention} 今日密码还没查到呢，稍等我再试一次。"
        tone = Tone.ERROR
    else:
        title = f"**今日作战密码 · {data.date}**"
        body = "\n".join(data.lines()) if data.lines() else "数据暂不可用"
        note = "数据每天早上更新，以游戏内为准哦。"
        core = f"{mention} {title}\n{body}\n{note}"
        tone = Tone.INFO
    return persona.render(
        core,
        PersonaContext(tone=tone, key=f"password-reply:{author_id}", mention=True),
    )


class KookBot:
    def __init__(
        self,
        token: str,
        password_cache: PasswordCache | None = None,
        persona: ArchitectPersona | None = None,
        state_path: str | Path = "data/kook_bot_state.json",
        trigger: str = "今日密码",
        bot_user_id: str | None = None,
    ):
        self.client = KookClient(token)
        self.cache = password_cache or PasswordCache("data/password_cache.json")
        self.persona = persona or ArchitectPersona(PersonaConfig())
        self.state_path = Path(state_path)
        self.trigger = trigger
        self.bot_user_id = bot_user_id
        self.last_sn = 0
        self.session_id: str | None = None

    def _load_state(self) -> None:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.last_sn = int(state.get("sn", 0) or 0)
            self.session_id = state.get("session_id") or None
        except (OSError, ValueError, TypeError):
            self.last_sn = 0
            self.session_id = None

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps({"sn": self.last_sn, "session_id": self.session_id}, ensure_ascii=False),
            encoding="utf-8",
        )

    def _clear_state(self) -> None:
        self.last_sn = 0
        self.session_id = None
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text("{}", encoding="utf-8")
        except OSError:
            pass

    def _gateway_url(self) -> str:
        data = self.client.gateway(compress=0)
        url = str(data.get("url") or "")
        if not url:
            raise RuntimeError("gateway 返回空 URL")
        if self.session_id:
            url += f"&resume=1&sn={self.last_sn}&session_id={self.session_id}"
        return url

    def _connect(self) -> websocket.WebSocket:
        url = self._gateway_url()
        ws = websocket.create_connection(url, timeout=6, enable_multithread=True)
        raw = ws.recv()
        hello = json.loads(raw)
        if hello.get("s") != 1 or int(hello.get("d", {}).get("code", -1)) != 0:
            ws.close()
            raise RuntimeError(f"HELLO 失败：{raw[:200]}")
        self.session_id = hello["d"].get("session_id") or self.session_id
        self._save_state()
        LOG.info("WebSocket 已连接，session=%s", self.session_id)
        return ws

    def refresh_password(self) -> None:
        cached = self.cache.get()
        if cached:
            LOG.debug("今日密码缓存命中：%s", cached.date)
        else:
            LOG.warning("今日密码获取失败，回复时会提示稍后重试")

    def handle_event(self, event: dict[str, Any]) -> None:
        if not should_reply(event, self.bot_user_id, self.trigger):
            return
        author_id = str(event["author_id"])
        channel_id = str(event["target_id"])
        data = self.cache.get()
        content = build_reply(data, author_id, self.persona)
        try:
            self.client.send_message(channel_id, content, msg_type=9)
            LOG.info("已在频道 %s 回复用户 %s", channel_id, author_id)
        except KookApiError as exc:
            LOG.error("回复失败：code=%s message=%s", exc.code, exc.message)

    def _listen(self, ws: websocket.WebSocket) -> None:
        heartbeat = 30 + random.randint(-5, 5)
        last_ping = time.monotonic()
        pong_deadline: float | None = None
        current_date = datetime.now(LOCAL_TZ).date().isoformat()

        while True:
            now_date = datetime.now(LOCAL_TZ).date().isoformat()
            if now_date != current_date:
                current_date = now_date
                self.cache.refresh(now_date)
                LOG.info("跨零点，已刷新今日密码缓存")

            ws.settimeout(1)
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                raw = None
            if raw:
                message = json.loads(raw)
                signal = int(message.get("s", -1))
                if signal == 0:
                    payload = message.get("d") or {}
                    self.last_sn = max(self.last_sn, int(message.get("sn", 0) or 0))
                    self.handle_event(payload)
                    self._save_state()
                elif signal == 3:
                    pong_deadline = None
                elif signal == 5:
                    LOG.warning("收到 RECONNECT，清空会话状态")
                    self._clear_state()
                    ws.close()
                    return
                elif signal == 6:
                    LOG.info("RESUME ACK，离线消息已补齐")
                    self._save_state()

            current = time.monotonic()
            if pong_deadline is not None and current > pong_deadline:
                raise TimeoutError("PONG 超时")
            if current - last_ping >= heartbeat:
                ws.send(json.dumps({"s": 2, "sn": self.last_sn}))
                last_ping = current
                pong_deadline = current + 6

    def run(self) -> None:
        self._load_state()
        if self.bot_user_id is None:
            try:
                self.bot_user_id = str(self.client.me().get("id") or "") or None
            except KookApiError as exc:
                LOG.warning("获取机器人自身 ID 失败：%s", exc.message)
        self.refresh_password()

        backoff = 2
        while True:
            try:
                ws = self._connect()
                backoff = 2
                self._listen(ws)
            except KeyboardInterrupt:
                LOG.info("监听已停止")
                return
            except Exception as exc:
                LOG.warning("连接中断：%s，%s 秒后重试", exc, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
