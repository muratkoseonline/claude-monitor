#!/usr/bin/env python3
"""
Claude Monitor - Simge üretici
icon.ico (çoklu boyut) + tray preview oluşturur.
"""

import math
from PIL import Image, ImageDraw, ImageFont

CLAUDE_PURPLE   = (124, 58,  237)   # #7C3AED
CLAUDE_LIGHT    = (167, 139, 250)   # #A78BFA
CLAUDE_DARK     = (46,  16,  101)   # #2E1065
CLAUDE_BG       = (30,  10,  60)    # koyu arka plan
WHITE           = (255, 255, 255)
TRANSPARENT     = (0,   0,   0,   0)


def draw_base(draw: ImageDraw.ImageDraw, size: int):
    """Claude logosunu çizer: koyu daire + parlak C harfi."""
    s = size

    # Dış daire — koyu mor dolgu
    draw.ellipse([0, 0, s - 1, s - 1], fill=(*CLAUDE_BG, 255))

    # İnce parlak halka
    ring = max(1, s // 20)
    draw.ellipse(
        [ring, ring, s - ring - 1, s - ring - 1],
        outline=(*CLAUDE_LIGHT, 180),
        width=max(1, ring),
    )

    # "C" harfi — arc ile
    pad   = int(s * 0.18)
    arc_w = max(2, int(s * 0.14))
    # Tam daire çiz, sonra üstüne arka plan rengiyle sağ dilimi kapat
    cx, cy = s / 2, s / 2
    r = s / 2 - pad

    # Yay: -150° → +150° (sağ taraf açık → C şekli)
    draw.arc(
        [pad, pad, s - pad - 1, s - pad - 1],
        start=40, end=320,
        fill=(*WHITE, 255),
        width=arc_w,
    )

    # Küçük nokta — sağ alt (AI spark)
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


def make_tray_icon(size: int, percent: int, error: bool = False, no_key: bool = False) -> Image.Image:
    """Tepsi için — base + yüzde metni + kullanım yayı."""
    img  = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(img)

    if no_key:
        draw.ellipse([0, 0, size - 1, size - 1], fill=(*CLAUDE_BG, 255))
        ring = max(1, size // 20)
        draw.ellipse([ring, ring, size - ring - 1, size - ring - 1],
                     outline=(100, 80, 140, 160), width=max(1, ring))
        text, color = "KEY", (120, 100, 170)
    elif error:
        draw.ellipse([0, 0, size - 1, size - 1], fill=(*CLAUDE_BG, 255))
        ring = max(1, size // 20)
        draw.ellipse([ring, ring, size - ring - 1, size - ring - 1],
                     outline=(180, 60, 60, 180), width=max(1, ring))
        text, color = "ERR", (200, 80, 80)
    else:
        draw_base(draw, size)

        # Kullanım yayı (dış kenar üstüne)
        if percent > 0:
            arc_pad = max(1, size // 16)
            arc_w   = max(2, size // 10)
            angle   = int(360 * percent / 100)
            if percent < 50:
                arc_col = (100, 220, 120, 220)
            elif percent < 75:
                arc_col = (255, 170, 50, 220)
            else:
                arc_col = (240, 70, 70, 220)
            draw.arc(
                [arc_pad, arc_pad, size - arc_pad - 1, size - arc_pad - 1],
                start=-90, end=-90 + angle,
                fill=arc_col,
                width=arc_w,
            )

        text  = f"{percent}%"
        color = WHITE

    # Yüzde metni
    font_size = int(size * (0.28 if len(text) <= 3 else 0.24))
    font = None
    for fname in ["arialbd.ttf", "arial.ttf", "segoeui.ttf"]:
        try:
            font = ImageFont.truetype(f"C:/Windows/Fonts/{fname}", font_size)
            break
        except:
            continue
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1]
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

    # Önizleme
    preview = make_tray_icon(128, 13)
    preview.save("icon_preview_13.png")
    preview2 = make_tray_icon(128, 78)
    preview2.save("icon_preview_78.png")
    print("Önizlemeler: icon_preview_13.png / icon_preview_78.png")
