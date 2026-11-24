#!/usr/bin/env python3
"""
Claude Monitor - Simge üretici
icon.ico (çoklu boyut) + 4 çeyrek yaylı tepsi simgesi oluşturur.
"""

import math
from PIL import Image, ImageDraw, ImageFont

CLAUDE_PURPLE   = (124, 58,  237)   # #7C3AED
CLAUDE_LIGHT    = (167, 139, 250)   # #A78BFA
CLAUDE_DARK     = (46,  16,  101)   # #2E1065
CLAUDE_BG       = (30,  10,  60)    # koyu arka plan
TRACK_COLOR     = (72,  56,  108, 150)
WHITE           = (255, 255, 255)
TRANSPARENT     = (0,   0,   0,   0)

# Dış halkadaki 4 eşit çeyrek yay (saat 12 = -90°, saat yönünde artar):
# Sağ-üst: Claude, Sağ-alt: Codex, Sol-alt: OpenCode Go, Sol-üst: Antigravity
_QUADRANTS = (
    (-85, -5),   # Claude
    (5, 85),     # Codex
    (95, 175),   # OpenCode Go
    (185, 265),  # Antigravity
)


def draw_base(draw: ImageDraw.ImageDraw, size: int):
    """Claude logosunu çizer: koyu daire + parlak C harfi."""
    s = size

    # Dış daire - koyu mor dolgu
    draw.ellipse([0, 0, s - 1, s - 1], fill=(*CLAUDE_BG, 255))

    # İnce parlak halka
    ring = max(1, s // 20)
    draw.ellipse(
        [ring, ring, s - ring - 1, s - ring - 1],
        outline=(*CLAUDE_LIGHT, 180),
        width=max(1, ring),
    )

    # "C" harfi - arc ile
    pad   = int(s * 0.18)
    arc_w = max(2, int(s * 0.14))
    cx, cy = s / 2, s / 2
    r = s / 2 - pad

    # Yay: 40° -> 320° (sağ taraf açık -> C şekli)
    draw.arc(
        [pad, pad, s - pad - 1, s - pad - 1],
        start=40, end=320,
        fill=(*WHITE, 255),
        width=arc_w,
    )

    # Küçük nokta - sağ alt (AI spark)
    dot_r = max(2, int(s * 0.09))
    dot_x = int(cx + r * math.cos(math.radians(-30)))
    dot_y = int(cy + r * math.sin(math.radians(-30)))
    draw.ellipse(
        [dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r],
        fill=(*CLAUDE_LIGHT, 255),
    )


def make_base_icon(size: int) -> Image.Image:
    img  = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(img)
    draw_base(draw, size)
    return img


def _arc_color(percent: float):
    if percent < 50:
        return (100, 220, 120, 235)
    if percent < 75:
        return (255, 170, 50, 235)
    return (240, 70, 70, 235)


def _draw_quadrant(draw: ImageDraw.ImageDraw, bbox, start_deg: int, end_deg: int,
                   width: int, percent, track_color=TRACK_COLOR):
    """Tek bir çeyrek yayın arka izini ve dolu kullanım kısmını çizer."""
    draw.arc(bbox, start=start_deg, end=end_deg, fill=track_color, width=width)
    if percent is None or percent <= 0:
        return
    clamped = max(0.0, min(100.0, float(percent)))
    span = end_deg - start_deg
    fill_end = start_deg + max(2, int(round(span * clamped / 100.0)))
    draw.arc(bbox, start=start_deg, end=min(end_deg, fill_end),
             fill=_arc_color(clamped), width=width)


def make_tray_icon(size: int, percent: int, error: bool = False, no_key: bool = False,
                   codex_percent=None, opencode_percent=None,
                   antigravity_percent=None) -> Image.Image:
    """Tepsi simgesi: koyu daire + dış halkada 4 eşit çeyrek yay + ortada Claude yüzdesi.

    Çeyrekler saat yönünde:
      Sağ-üst: Claude | Sağ-alt: Codex | Sol-alt: OpenCode Go | Sol-üst: Antigravity
    """
    img  = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(img)

    # Koyu arka plan dairesi (ortadaki metnin yüksek kontrastlı kalması için)
    draw.ellipse([0, 0, size - 1, size - 1], fill=(*CLAUDE_BG, 255))

    arc_pad = max(1, size // 24)
    arc_w   = max(3, size // 9)
    bbox    = [arc_pad, arc_pad, size - arc_pad - 1, size - arc_pad - 1]

    if no_key:
        claude_pct = None
        claude_track = (100, 80, 140, 160)
        text, color = "KEY", (160, 140, 210)
    elif error:
        claude_pct = None
        claude_track = (180, 60, 60, 190)
        text, color = "ERR", (230, 95, 95)
    else:
        claude_pct = percent
        claude_track = TRACK_COLOR
        text, color = f"{int(round(percent))}%", WHITE

    values = (claude_pct, codex_percent, opencode_percent, antigravity_percent)
    tracks = (claude_track, TRACK_COLOR, TRACK_COLOR, TRACK_COLOR)
    for (start_deg, end_deg), val, trk in zip(_QUADRANTS, values, tracks):
        _draw_quadrant(draw, bbox, start_deg, end_deg, arc_w, val, track_color=trk)

    # Ortada yüzde / durum metni (yaylarla çakışmaz)
    font_size = int(size * (0.29 if len(text) <= 3 else 0.23))
    font = None
    for fname in ["arialbd.ttf", "arial.ttf", "segoeui.ttf"]:
        try:
            font = ImageFont.truetype(f"C:/Windows/Fonts/{fname}", font_size)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    bbox_txt = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox_txt[2] - bbox_txt[0], bbox_txt[3] - bbox_txt[1]
    x = (size - tw) // 2 - bbox_txt[0]
    y = (size - th) // 2 - bbox_txt[1]
    draw.text((x, y), text, fill=(*color, 255), font=font)

    return img


def generate_ico(path: str = "icon.ico"):
    """16/32/48/64/128/256 px boyutlarında .ico üret."""
    sizes  = [256, 128, 64, 48, 32, 16]
    images = [make_base_icon(s) for s in sizes]
    images[0].save(
        path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    print(f"Simge kaydedildi: {path}")
    return path


if __name__ == "__main__":
    generate_ico()
    preview = make_tray_icon(128, 13, codex_percent=42, opencode_percent=65, antigravity_percent=85)
    preview.save("icon_preview_dual.png")
    print("Önizleme: icon_preview_dual.png")
