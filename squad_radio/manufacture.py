"""Fetch and format hourly manufacture recommendations from g.aitags.cn.

The page is server-rendered: all level/rank variants are present in the HTML and
the browser only toggles blocks / re-sorts rows.  We therefore parse the HTML
directly with the standard library -- no browser or third-party dependency.
"""
from __future__ import annotations

import html as html_module
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_URL = "https://g.aitags.cn/manufacture"
# 海外节点直连 g.aitags.cn 会超时；Google Translate 代理能返回同样带
# data-hour / data-total 的完整 HTML，作为云端兜底源。
TRANSLATE_URL = (
    "https://g-aitags-cn.translate.goog/manufacture"
    "?_x_tr_sl=zh-CN&_x_tr_tl=en&_x_tr_hl=en"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

_DEPARTMENT_ORDER = ("技术中心", "工作台", "制药台", "防具台")

_CARD_RE = re.compile(
    r'<ul class="df-card-list[^"]*" data-limit="(\d+)">(.*?)</ul>',
    re.DOTALL,
)
_ROW_RE = re.compile(r'<li class="df-row.*?</li>', re.DOTALL)
_DEPT_RE = re.compile(r'text-sm font-bold text-white truncate">([^<]+)<')
_NAME_RE = re.compile(
    r'text-sm font-bold text-slate-900 dark:text-white truncate leading-5">([^<]+)<'
)
_META_RE = re.compile(
    r'text-xs text-slate-400 truncate leading-4 h-4" title="([^"]+)">'
)
_UPDATE_RE = re.compile(r"数据自动更新于：\s*([^<·]+?)\s*·")


@dataclass(frozen=True)
class CraftRecommendation:
    department: str
    item: str
    category: str
    duration_hours: str
    total_profit: int
    hourly_profit: int
    unlock_level: str = ""
    fee_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "department": self.department,
            "item": self.item,
            "category": self.category,
            "duration_hours": self.duration_hours,
            "total_profit": self.total_profit,
            "hourly_profit": self.hourly_profit,
            "unlock_level": self.unlock_level,
            "fee_note": self.fee_note,
        }


def _unescape(value: str) -> str:
    return html_module.unescape(value).strip()


def _extract_level_block(page: str, level: int) -> str:
    marker = f'data-level="{level}"'
    idx = page.find(marker)
    if idx < 0:
        raise ValueError(f"页面中没有找到等级 {level} 的数据块")
    start = page.rfind('<div class="df-level-block', 0, idx)
    if start < 0:
        raise ValueError("页面结构异常：找不到数据块起始标签")

    candidates = [
        pos
        for pos in (
            page.find('<div class="df-level-block', idx + len(marker)),
            page.find("<script>", idx + len(marker)),
        )
        if pos >= 0
    ]
    end = min(candidates) if candidates else len(page)
    return page[start:end]


def _int_attr(row: str, name: str) -> int:
    match = re.search(rf'{name}="([^"]+)"', row)
    if not match:
        return 0
    return int(match.group(1).replace(",", "").strip() or 0)


def _parse_row(row: str, department: str) -> CraftRecommendation | None:
    name_match = _NAME_RE.search(row)
    if not name_match:
        return None

    title_match = re.search(r'title="([^"]+)"', row)
    title = _unescape(title_match.group(1)) if title_match else ""
    meta_match = _META_RE.search(row)
    meta = _unescape(meta_match.group(1)) if meta_match else ""

    duration_match = re.search(r"制造时长\s*([\d.]+)\s*小时", title)
    unlock_match = re.search(r"解锁\s*(Lv\.\d+)", title)
    fee_match = re.search(r"手续费\s*([\d,]+)", title)

    return CraftRecommendation(
        department=department,
        item=_unescape(name_match.group(1)),
        category=meta.split("·", 1)[0].strip() if "·" in meta else meta,
        duration_hours=meta.split("·", 1)[1].strip() if "·" in meta else "",
        total_profit=_int_attr(row, "data-total"),
        hourly_profit=_int_attr(row, "data-hour"),
        unlock_level=unlock_match.group(1) if unlock_match else "",
        fee_note=f"手续费 {fee_match.group(1)}" if fee_match else "",
    )


def parse_manufacture_page(
    page: str,
    *,
    level: int = 3,
    rank_type: str = "hour",
    top_per_department: int = 1,
) -> tuple[str, list[CraftRecommendation]]:
    """Parse a downloaded page into an update stamp and ranked recommendations."""
    block = _extract_level_block(page, level)
    update_match = _UPDATE_RE.search(page)
    update = _unescape(update_match.group(1)) if update_match else "时间未知"

    key = "hourly_profit" if rank_type == "hour" else "total_profit"
    recommendations: list[CraftRecommendation] = []

    for card in _CARD_RE.finditer(block):
        limit = int(card.group(1) or 5)
        before = block[: card.start()]
        dept_matches = _DEPT_RE.findall(before)
        department = _unescape(dept_matches[-1]) if dept_matches else "制造台"

        rows = [_parse_row(row, department) for row in _ROW_RE.findall(card.group(2))]
        rows = [row for row in rows if row is not None]
        rows.sort(key=lambda item: getattr(item, key), reverse=True)
        recommendations.extend(rows[: min(limit, max(0, top_per_department))])

    return update, recommendations


def _download_page(url: str, level: int, rank_type: str, timeout: int) -> str:
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(parts.query)
    query.update({"level": [str(level)], "rank_type": [rank_type]})
    target = urllib.parse.urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urllib.parse.urlencode(query, doseq=True),
            parts.fragment,
        )
    )
    request = urllib.request.Request(
        target,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_manufacture_recommendations(
    *,
    level: int = 3,
    rank_type: str = "hour",
    top_per_department: int = 1,
    timeout: int = 15,
    url: str = DEFAULT_URL,
    fallback_url: str = TRANSLATE_URL,
) -> tuple[str, list[CraftRecommendation]]:
    """Download the board and return the freshest recommendations.

    Tries the direct site first; on network failure falls back to the Google
    Translate proxy, which returns the same server-rendered HTML and works
    from overseas nodes that cannot reach the Chinese origin directly.
    """
    candidates = [url]
    if fallback_url and url not in (fallback_url, TRANSLATE_URL):
        candidates.append(fallback_url)

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            page = _download_page(candidate, level, rank_type, timeout)
            return parse_manufacture_page(
                page,
                level=level,
                rank_type=rank_type,
                top_per_department=top_per_department,
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc

    raise last_error or RuntimeError("没有可用的制造榜数据源")


def format_manufacture_broadcast(
    update: str,
    recommendations: list[CraftRecommendation],
    *,
    level: int = 3,
    rank_type: str = "hour",
) -> str:
    """Render a compact KOOK KMarkdown broadcast."""
    rank_label = "小时利润" if rank_type == "hour" else "总利润"
    lines = [
        f"**🏭 特勤处制造推荐 · {level}级 · 按{rank_label}**",
        "",
        f"数据更新：{update} ｜ 来源：g.aitags.cn",
        "",
    ]

    departments = [dept for dept in _DEPARTMENT_ORDER if any(r.department == dept for r in recommendations)]
    departments.extend(
        sorted({r.department for r in recommendations} - set(_DEPARTMENT_ORDER))
    )

    for department in departments:
        lines.append(f"**{department}**")
        group = [r for r in recommendations if r.department == department]
        for index, rec in enumerate(group, 1):
            lines.append(
                f"{index}. {rec.item} — `{rec.hourly_profit:,}/h`"
                f"（总 {rec.total_profit:,} · {rec.duration_hours}）"
            )
        lines.append("")

    lines.append("> 指挥官，按小时利润排的，先看一眼再施工哦。")
    return "\n".join(lines).strip()


def recommendations_to_json(
    update: str, recommendations: list[CraftRecommendation]
) -> str:
    return json.dumps(
        {"update": update, "recommendations": [r.to_dict() for r in recommendations]},
        ensure_ascii=False,
        indent=2,
    )
