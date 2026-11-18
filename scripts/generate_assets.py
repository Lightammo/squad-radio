"""Generate Squad Radio broadcast banner images with Pillow.

Design: dark tactical briefing style with gradient, grid, hazard stripes,
hexagons and a bold title. Outputs PNG files used as KOOK link thumbnails.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 880, 340

# theme: (top_color, bottom_color, accent, badge_text)
THEMES = {
    "password": ((10, 24, 42), (20, 52, 82), (86, 214, 231), "DAILY CODE"),
    "red": ((34, 10, 14), (104, 28, 34), (255, 202, 76), "HIGH VALUE"),
    "market": ((20, 18, 10), (86, 58, 16), (255, 143, 24), "MARKET ALERT"),
    "task": ((8, 28, 20), (22, 74, 48), (102, 221, 138), "TASK DONE"),
}

CN_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
]
EN_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _gradient(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        t = y / max(1, H - 1)
        # slight vignette toward edges
        row = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(W):
            vx = 1 - 0.28 * (abs(x - W / 2) / (W / 2)) ** 2
            px[x, y] = tuple(max(0, min(255, int(c * vx))) for c in row)
    return img


def _grid(draw: ImageDraw.ImageDraw, accent: tuple[int, int, int]) -> None:
    grid = (*accent[:3], 26)
    for x in range(0, W, 40):
        draw.line([(x, 0), (x, H)], fill=grid, width=1)
    for y in range(0, H, 40):
        draw.line([(0, y), (W, y)], fill=grid, width=1)


def _hazard(draw: ImageDraw.ImageDraw, accent: tuple[int, int, int]) -> None:
    """Diagonal hazard stripes in the bottom-left corner."""
    stripe = (*accent, 46)
    for i in range(-H, W, 26):
        draw.polygon(
            [(i, H), (i + 13, H), (i + 13 + 90, H - 46), (i + 90, H - 46)],
            fill=stripe,
        )


def _hexagon(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    r: float,
    fill: tuple[int, ...],
    outline: tuple[int, ...] | None = None,
    width: int = 2,
) -> None:
    pts = [
        (cx + r * math.cos(math.radians(60 * k)), cy + r * math.sin(math.radians(60 * k)))
        for k in range(6)
    ]
    draw.polygon(pts, fill=fill)
    if outline:
        draw.line(pts + [pts[0]], fill=outline, width=width, joint="curve")


def _crosshair(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, color: tuple[int, ...]) -> None:
    draw.arc([cx - r, cy - r, cx + r, cy + r], 0, 360, fill=color, width=2)
    draw.line([(cx - r - 10, cy), (cx - r + 6, cy)], fill=color, width=2)
    draw.line([(cx + r - 6, cy), (cx + r + 10, cy)], fill=color, width=2)
    draw.line([(cx, cy - r - 10), (cx, cy - r + 6)], fill=color, width=2)
    draw.line([(cx, cy + r - 6), (cx, cy + r + 10)], fill=color, width=2)


def render(title: str, subtitle: str, theme: str, output: str | Path) -> Path:
    top, bottom, accent, badge = THEMES[theme]
    base = _gradient(top, bottom).convert("RGBA")
    grid_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid_layer)
    _grid(gd, accent)
    _hazard(gd, accent)
    base = Image.alpha_composite(base, grid_layer)
    draw = ImageDraw.Draw(base)

    # left accent bar
    draw.rectangle([0, 0, 9, H], fill=(*accent, 255))
    draw.rectangle([14, 30, 17, H - 30], fill=(*accent, 90))

    # tactical decorations on the right
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    for idx, (hx, hy, hr) in enumerate([(720, 92, 58), (792, 168, 40), (690, 220, 26)]):
        _hexagon(dd, hx, hy, hr, (*accent, 22), (*accent, 70), 2)
    _crosshair(dd, 634, 96, 30, (*accent, 110))
    for i in range(5):
        y = 250 + i * 14
        dd.line([(748, y), (748 + (40 - i * 6), y)], fill=(*accent, 90), width=3)
    base = Image.alpha_composite(base, deco)
    draw = ImageDraw.Draw(base)

    cn = _font(CN_FONT_CANDIDATES, 76)
    en = _font(EN_FONT_CANDIDATES, 25)
    badge_font = _font(EN_FONT_CANDIDATES, 22)

    # badge chip
    draw.rounded_rectangle([40, 40, 40 + 22 * len(badge) + 26, 82], radius=12, fill=(*accent, 235))
    draw.text((53, 48), badge, font=badge_font, fill=(10, 16, 26, 255))

    # glow-ish title (draw offset shadow then main)
    shadow = (0, 0, 0, 150)
    draw.text((44, 116), title, font=cn, fill=shadow, stroke_width=0)
    draw.text((40, 112), title, font=cn, fill=(244, 249, 255, 255))
    # accent underline
    draw.line([(44, 214), (44 + min(360, 34 * len(title)), 214)], fill=(*accent, 255), width=6)

    # subtitle
    draw.text((44, 246), subtitle, font=en, fill=(*accent, 235))

    # bottom-right signature
    sig = "SQUAD RADIO // ARCHITECT"
    sw = draw.textlength(sig, font=en)
    draw.text((W - sw - 34, H - 52), sig, font=en, fill=(200, 214, 230, 150))

    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(path, "PNG", optimize=True)
    return path


def main() -> None:
    here = Path(__file__).resolve().parent.parent / "data" / "assets"
    here.mkdir(parents=True, exist_ok=True)
    specs = [
        ("password", "今日作战密码", "DAILY OPERATION CODE // DELTA FORCE", "password_banner.png"),
        ("red", "高价值物资", "HIGH VALUE ITEM ACQUIRED", "red_banner.png"),
        ("market", "物价异动预警", "MARKET PRICE MOVEMENT ALERT", "market_banner.png"),
        ("task", "特勤处完工", "FACILITY CONSTRUCTION COMPLETE", "task_banner.png"),
    ]
    for theme, title, subtitle, filename in specs:
        out = render(title, subtitle, theme, here / filename)
        print(f"{theme:9s} -> {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
