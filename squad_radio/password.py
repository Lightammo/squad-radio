"""Daily Delta Force password cache.

The cache is keyed by Asia/Shanghai calendar date. At startup and whenever the
date rolls over, the bot refreshes it from a public JSON endpoint; a text
endpoint is kept as a fallback. A successful refresh replaces the old file.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import LOCAL_TZ

DEFAULT_PASSWORD_URL = "https://db.18183.com/sjzmm/data/daily/{date}.json"
FALLBACK_PASSWORD_URL = "https://www.tmini.net/api/sjzmm?ckey=&type="
# 海外节点（如泰国）直连国内 CDN 常 8s 超时，而此时备源 tmini 还停留在昨天，
# 导致跨零点后整晚拿不到当日密码。用公开 reader 代理转发同一主源 JSON 作为兜底：
# 它返回 "Markdown Content:\n{...}" 文本，需从中抽出 JSON 再走同样的严格校验。
READER_PROXY_PREFIX = "https://r.jina.ai/"
REQUIRED_MAPS = ("零号大坝", "长弓溪谷", "巴克什", "航天基地", "潮汐监狱", "AZ3")


@dataclass
class PasswordData:
    date: str
    entries: dict[str, str]
    source: str
    fetched_at: str
    stale: bool = False

    def lines(self) -> list[str]:
        return [f"{name}：`{self.entries[name]}`" for name in REQUIRED_MAPS if name in self.entries]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PasswordData | None":
        try:
            return cls(
                date=str(raw["date"]),
                entries={str(k): str(v) for k, v in dict(raw["entries"]).items()},
                source=str(raw.get("source", "unknown")),
                fetched_at=str(raw.get("fetched_at", "")),
                stale=bool(raw.get("stale", False)),
            )
        except (KeyError, TypeError, ValueError):
            return None


def parse_reader_payload(text: str) -> dict[str, Any] | None:
    """从 reader 代理的包装文本中抽出 JSON 对象（Markdown Content 段）。"""
    marker = "Markdown Content:"
    body = text.split(marker, 1)[1] if marker in text else text
    start = body.find("{")
    if start < 0:
        return None
    try:
        raw = json.loads(body[start:])
    except (ValueError, TypeError):
        # 代理有时会在 JSON 后附带额外说明文字，退一步用 raw_decode 精确截断
        try:
            raw, _ = json.JSONDecoder().raw_decode(body[start:])
        except (ValueError, TypeError):
            return None
    return raw if isinstance(raw, dict) else None


def _valid_entries(entries: dict[str, str]) -> bool:
    return all(
        re.fullmatch(r"\d{4}", str(entries.get(name, ""))) for name in REQUIRED_MAPS
    )


def parse_json_payload(raw: dict[str, Any], date: str, url: str) -> PasswordData | None:
    if str(raw.get("date", "")) != date:
        return None
    entries = raw.get("entries")
    if not isinstance(entries, dict) or not _valid_entries(entries):
        return None
    return PasswordData(
        date=date,
        entries={name: str(entries[name]) for name in REQUIRED_MAPS},
        source=url,
        fetched_at=datetime.now(LOCAL_TZ).isoformat(),
    )


def parse_text_payload(text: str, date: str, url: str) -> PasswordData | None:
    dt = datetime.strptime(date, "%Y-%m-%d")
    expected = f"{dt.month}月{dt.day}日"
    if expected not in text:
        return None
    pairs = re.findall(r"地图名称:\s*(.+?)\n密码:\s*(\d{4})", text)
    entries = {name.strip(): code for name, code in pairs}
    # 注意：不能在这里用 _valid_entries 直接校验，备源把 AZ3 写作「AZ3核电站」，
    # 必须先归一化再校验，否则备源永远返回 None（2026-11-19 修复）。
    normalized = {}
    for name in REQUIRED_MAPS:
        if name == "AZ3":
            normalized[name] = entries.get("AZ3核电站", entries.get("AZ3", ""))
        else:
            normalized[name] = entries.get(name, "")
    if not _valid_entries(normalized):
        return None
    return PasswordData(
        date=date,
        entries=normalized,
        source=url,
        fetched_at=datetime.now(LOCAL_TZ).isoformat(),
    )


class PasswordCache:
    def __init__(
        self,
        path: str | Path,
        url_template: str = DEFAULT_PASSWORD_URL,
        fallback_url: str = FALLBACK_PASSWORD_URL,
        reader_prefix: str = READER_PROXY_PREFIX,
        timeout: int = 8,
    ):
        self.path = Path(path)
        self.url_template = url_template
        self.fallback_url = fallback_url
        self.reader_prefix = reader_prefix
        self.timeout = timeout

    def _read(self) -> PasswordData | None:
        if not self.path.exists():
            return None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return PasswordData.from_dict(raw)

    def _write(self, data: PasswordData) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def _get(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": "SquadRadio/0.1"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    def fetch(self, date: str) -> PasswordData | None:
        primary = self.url_template.replace("{date}", date)
        try:
            data = parse_json_payload(json.loads(self._get(primary)), date, primary)
            if data:
                return data
        except (OSError, ValueError, TypeError):
            pass

        # 主源超时（海外节点直连国内 CDN）时，经 reader 代理取同一份 JSON。
        # 代理内容与主源完全一致，仍经过 parse_json_payload 的日期+六图校验。
        if self.reader_prefix:
            try:
                raw = parse_reader_payload(self._get(self.reader_prefix + primary))
                if raw:
                    data = parse_json_payload(raw, date, primary)
                    if data:
                        return data
            except (OSError, ValueError, TypeError):
                pass

        if self.fallback_url:
            try:
                return parse_text_payload(self._get(self.fallback_url), date, self.fallback_url)
            except OSError:
                pass
        return None

    def refresh(self, date: str | None = None) -> PasswordData | None:
        target = date or datetime.now(LOCAL_TZ).date().isoformat()
        fresh = self.fetch(target)
        if fresh:
            self._write(fresh)
            return fresh
        cached = self._read()
        if cached and cached.date == target:
            cached.stale = True
            return cached
        return None

    def get(self, now: datetime | None = None, force: bool = False) -> PasswordData | None:
        current = (now or datetime.now(LOCAL_TZ)).astimezone(LOCAL_TZ)
        date = current.date().isoformat()
        cached = self._read()
        if cached and cached.date == date and not force and not cached.stale:
            return cached
        return self.refresh(date)
