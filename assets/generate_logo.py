#!/usr/bin/env python3
"""
Generate the LUTH logo — a robot head symbolizing automation.
Creates luth_logo.png and luth.ico in the assets/ directory.

Run: python assets/generate_logo.py
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = Path(__file__).parent
SIZE = 512
HALF = SIZE // 2


def draw_robot_head(size: int = SIZE) -> Image.Image:
    """Draw a stylized robot/automation head logo for LUTH."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Colors
    bg_dark = (26, 26, 46)        # #1a1a2e
    accent_red = (233, 69, 96)    # #e94560
    accent_blue = (15, 52, 96)    # #0f3460
    gold = (255, 193, 7)          # #ffc107
    white = (238, 238, 238)
    dark_card = (22, 33, 62)      # #16213e

    # Background circle
    pad = 20
    draw.ellipse([pad, pad, size - pad, size - pad], fill=bg_dark, outline=accent_blue, width=4)

    # Robot head (rounded rectangle)
    head_l, head_t = 120, 100
    head_r, head_b = size - 120, size - 160
    draw.rounded_rectangle([head_l, head_t, head_r, head_b], radius=30,
                            fill=dark_card, outline=accent_red, width=3)

    # Antenna
    ant_cx = HALF
    ant_top = 55
    ant_base = head_t
    draw.line([(ant_cx, ant_base), (ant_cx, ant_top + 20)], fill=accent_red, width=4)
    draw.ellipse([ant_cx - 10, ant_top, ant_cx + 10, ant_top + 20], fill=gold)

    # Eyes (glowing circles)
    eye_y = 180
    eye_r = 28
    # Left eye
    draw.ellipse([170 - eye_r, eye_y - eye_r, 170 + eye_r, eye_y + eye_r],
                  fill=accent_red, outline=gold, width=2)
    # Right eye
    draw.ellipse([size - 170 - eye_r, eye_y - eye_r, size - 170 + eye_r, eye_y + eye_r],
                  fill=accent_red, outline=gold, width=2)

    # Eye highlights
    hl = 8
    draw.ellipse([170 - hl + 8, eye_y - hl - 5, 170 + hl + 8, eye_y + hl - 5], fill=white)
    draw.ellipse([size - 170 - hl + 8, eye_y - hl - 5, size - 170 + hl + 8, eye_y + hl - 5], fill=white)

    # Mouth (audio waveform bars)
    mouth_y = 270
    bar_w = 12
    bar_gap = 8
    bar_heights = [15, 30, 22, 35, 22, 30, 15]
    total_w = len(bar_heights) * bar_w + (len(bar_heights) - 1) * bar_gap
    start_x = HALF - total_w // 2

    for i, h in enumerate(bar_heights):
        x = start_x + i * (bar_w + bar_gap)
        y_top = mouth_y - h // 2
        y_bot = mouth_y + h // 2
        draw.rounded_rectangle([x, y_top, x + bar_w, y_bot], radius=4, fill=gold)

    # Ear bolts
    bolt_r = 12
    draw.ellipse([head_l - bolt_r - 5, 190 - bolt_r, head_l + bolt_r - 5, 190 + bolt_r],
                  fill=accent_blue, outline=accent_red, width=2)
    draw.ellipse([head_r - bolt_r + 5, 190 - bolt_r, head_r + bolt_r + 5, 190 + bolt_r],
                  fill=accent_blue, outline=accent_red, width=2)

    # Gear icons (small, on sides — symbolize automation)
    _draw_gear(draw, 80, size - 120, 25, accent_blue, accent_red)
    _draw_gear(draw, size - 80, size - 120, 25, accent_blue, accent_red)

    # "LUTH" text at bottom
    try:
        font = ImageFont.truetype("arialbd.ttf", 52)
    except OSError:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
        except OSError:
            font = ImageFont.load_default()

    text = "LUTH"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    tx = HALF - tw // 2
    ty = size - 130

    # Text shadow
    draw.text((tx + 2, ty + 2), text, fill=(0, 0, 0, 180), font=font)
    # Text
    draw.text((tx, ty), text, fill=white, font=font)

    return img


def _draw_gear(draw: ImageDraw.Draw, cx: int, cy: int, r: int, fill, outline):
    """Draw a simple gear icon."""
    import math
    # Inner circle
    draw.ellipse([cx - r * 0.5, cy - r * 0.5, cx + r * 0.5, cy + r * 0.5],
                  fill=fill, outline=outline, width=2)
    # Teeth (8 small rectangles around the circle)
    tooth_w = r * 0.3
    tooth_h = r * 0.4
    for i in range(8):
        angle = math.radians(i * 45)
        tx = cx + r * 0.7 * math.cos(angle)
        ty = cy + r * 0.7 * math.sin(angle)
        draw.ellipse([tx - tooth_w, ty - tooth_w, tx + tooth_w, ty + tooth_w],
                      fill=fill, outline=outline, width=1)


def main():
    logo = draw_robot_head(512)

    # Save PNG
    png_path = ASSETS_DIR / "luth_logo.png"
    logo.save(str(png_path), "PNG")
    print(f"Logo saved: {png_path}")

    # Save ICO (multiple sizes for Windows)
    ico_path = ASSETS_DIR / "luth.ico"
    sizes = [16, 32, 48, 64, 128, 256]
    icons = []
    for s in sizes:
        icons.append(logo.resize((s, s), Image.LANCZOS))
    icons[0].save(str(ico_path), format="ICO", sizes=[(s, s) for s in sizes],
                   append_images=icons[1:])
    print(f"Icon saved: {ico_path}")

    # Save a smaller version for the GUI
    small = logo.resize((64, 64), Image.LANCZOS)
    small_path = ASSETS_DIR / "luth_64.png"
    small.save(str(small_path), "PNG")
    print(f"Small logo saved: {small_path}")


if __name__ == "__main__":
    main()
