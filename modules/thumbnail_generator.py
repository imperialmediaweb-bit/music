import random
import time
from pathlib import Path
import requests
from io import BytesIO
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from config import OPENAI_API_KEY, OUTPUT_DIR, THUMBNAIL_TEXT_STYLE
from utils.logger import log


def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a bold font at the given size, with fallbacks."""
    for font_name in [
        "Impact", "Arial Bold", "arialbd.ttf",
        "DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        try:
            return ImageFont.truetype(font_name, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _measure_and_scale_text(draw, text, font_size, width, height):
    """Measure text and auto-scale font if too wide.

    Returns (font, text_w, text_h, offset_x, offset_y) where offset_x/y are
    the bbox origin offsets needed to correctly position text.
    """
    font = _get_font(font_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    max_width = int(width * 0.9)
    if text_w > max_width:
        font_size = int(font_size * max_width / text_w)
        font = _get_font(font_size)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

    return font, text_w, text_h, bbox[0], bbox[1]


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color string to RGB tuple."""
    hex_color = hex_color.lstrip("#")
    return (int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))


def _add_text_classic(
    image: Image.Image,
    text: str,
    y_ratio: float,
    font_size_ratio: float,
    color: str = "#FFD700",
) -> Image.Image:
    """Original text overlay with hard black outline (classic style)."""
    draw = ImageDraw.Draw(image)
    width, height = image.size

    font_size = int(height * font_size_ratio)
    text = text.upper()
    font, text_w, text_h, off_x, off_y = _measure_and_scale_text(draw, text, font_size, width, height)

    # bbox_left is where we want the text bbox to start
    bbox_left = (width - text_w) // 2
    bbox_top = int(height * y_ratio) - text_h // 2

    # draw.text origin must be shifted by the bbox offsets
    x = bbox_left - off_x
    y = bbox_top - off_y

    # Semi-transparent dark band behind text for readability
    pad_v = int(text_h * 0.3)
    band = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    band_draw = ImageDraw.Draw(band)
    band_draw.rectangle(
        [0, bbox_top - pad_v, width, bbox_top + text_h + pad_v],
        fill=(0, 0, 0, 150),
    )
    image = image.convert("RGBA")
    image = Image.alpha_composite(image, band)
    image = image.convert("RGB")
    draw = ImageDraw.Draw(image)

    outline_width = max(3, font_size // 12)
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx * dx + dy * dy <= outline_width * outline_width:
                draw.text((x + dx, y + dy), text, font=font, fill="black")

    draw.text((x, y), text, font=font, fill=color)
    return image


def _add_stylized_text(
    image: Image.Image,
    text: str,
    y_ratio: float,
    font_size_ratio: float,
    color_top: str = "#FFD700",
    color_bottom: str = "#FFFFFF",
    glow: bool = True,
    divider: bool = False,
) -> Image.Image:
    """Premium text overlay with soft shadow, neon glow, and gradient fill.

    Composites multiple RGBA layers for a professional album-cover look.
    """
    width, height = image.size
    image = image.convert("RGBA")

    font_size = int(height * font_size_ratio)
    text = text.upper()

    # Measure text on a temp draw
    tmp = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp)
    font, text_w, text_h, off_x, off_y = _measure_and_scale_text(tmp_draw, text, font_size, width, height)

    # bbox_left/bbox_top = where we want the text bounding box placed
    bbox_left = (width - text_w) // 2
    bbox_top = int(height * y_ratio) - text_h // 2

    # draw.text origin must be shifted by the bbox offsets
    draw_x = bbox_left - off_x
    draw_y = bbox_top - off_y

    # --- Layer 0: Semi-transparent dark band for readability ---
    pad_v = int(text_h * 0.3)
    band = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    band_draw = ImageDraw.Draw(band)
    band_draw.rectangle(
        [0, bbox_top - pad_v, width, bbox_top + text_h + pad_v],
        fill=(0, 0, 0, 150),
    )
    image = Image.alpha_composite(image, band)

    # --- Layer 1: Soft drop shadow ---
    shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_offset_x, shadow_offset_y = 4, 6
    shadow_draw.text(
        (draw_x + shadow_offset_x, draw_y + shadow_offset_y), text,
        font=font, fill=(0, 0, 0, 180),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=8))
    image = Image.alpha_composite(image, shadow)

    # --- Layer 2: Neon glow ---
    if glow:
        glow_color = _hex_to_rgb(color_top)
        glow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_layer)
        # Wide dim glow
        glow_draw.text(
            (draw_x, draw_y), text, font=font,
            fill=(*glow_color, 40),
            stroke_width=6, stroke_fill=(*glow_color, 30),
        )
        # Medium glow
        glow_draw.text(
            (draw_x, draw_y), text, font=font,
            fill=(*glow_color, 70),
            stroke_width=3, stroke_fill=(*glow_color, 50),
        )
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=4))
        image = Image.alpha_composite(image, glow_layer)

    # --- Layer 3: Gradient-filled text ---
    # Create vertical gradient strip the size of the text
    top_rgb = _hex_to_rgb(color_top)
    bot_rgb = _hex_to_rgb(color_bottom)
    gradient = Image.new("RGBA", (text_w, text_h), (0, 0, 0, 0))
    for row in range(text_h):
        ratio = row / max(text_h - 1, 1)
        r = int(top_rgb[0] + (bot_rgb[0] - top_rgb[0]) * ratio)
        g = int(top_rgb[1] + (bot_rgb[1] - top_rgb[1]) * ratio)
        b = int(top_rgb[2] + (bot_rgb[2] - top_rgb[2]) * ratio)
        for col in range(text_w):
            gradient.putpixel((col, row), (r, g, b, 255))

    # Create text mask — draw at (-off_x, -off_y) so the full glyph fits
    mask = Image.new("L", (text_w, text_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text((-off_x, -off_y), text, font=font, fill=255)

    # Apply mask to gradient
    gradient.putalpha(mask)

    # Paste gradient text onto image at the bbox position
    image.paste(gradient, (bbox_left, bbox_top), gradient)

    # --- Layer 4: Decorative divider line ---
    if divider and text_w > 20:
        div_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        div_draw = ImageDraw.Draw(div_layer)
        line_w = int(text_w * 0.6)
        line_y = bbox_top + text_h + int(text_h * 0.3)
        line_x1 = (width - line_w) // 2
        line_x2 = line_x1 + line_w
        glow_rgb = _hex_to_rgb(color_top)
        div_draw.line(
            [(line_x1, line_y), (line_x2, line_y)],
            fill=(*glow_rgb, 120), width=2,
        )
        # Small dots at each end
        dot_r = 3
        div_draw.ellipse(
            [line_x1 - dot_r, line_y - dot_r, line_x1 + dot_r, line_y + dot_r],
            fill=(*glow_rgb, 160),
        )
        div_draw.ellipse(
            [line_x2 - dot_r, line_y - dot_r, line_x2 + dot_r, line_y + dot_r],
            fill=(*glow_rgb, 160),
        )
        image = Image.alpha_composite(image, div_layer)

    return image.convert("RGB")


def _add_track_name(image: Image.Image, track_name: str) -> Image.Image:
    """Overlay the track name in bold stylized text in the lower third."""
    if THUMBNAIL_TEXT_STYLE == "classic":
        return _add_text_classic(image, track_name, y_ratio=0.78, font_size_ratio=0.12)
    return _add_stylized_text(
        image, track_name, y_ratio=0.78, font_size_ratio=0.12,
        color_top="#FFD700", color_bottom="#FFFFFF", glow=True, divider=True,
    )


def _add_cover_name_only(image: Image.Image, track_name: str) -> Image.Image:
    """Overlay ONLY the track name on the cover, no band/glow/divider.

    Minimal clean text with a thin outline for legibility against any background.
    Used for TuneCore cover art where only the song name should appear.
    """
    image = image.convert("RGB")
    draw = ImageDraw.Draw(image)
    width, height = image.size

    text = track_name.upper()
    font_size = int(height * 0.10)
    font, text_w, text_h, off_x, off_y = _measure_and_scale_text(
        draw, text, font_size, width, height
    )

    bbox_left = (width - text_w) // 2
    bbox_top = int(height * 0.78) - text_h // 2
    x = bbox_left - off_x
    y = bbox_top - off_y

    outline_width = max(2, font_size // 20)
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx * dx + dy * dy <= outline_width * outline_width:
                draw.text((x + dx, y + dy), text, font=font, fill="black")

    draw.text((x, y), text, font=font, fill="white")
    return image


def _tagline_from_title(youtube_title: str) -> str:
    """Derive a short benefit tagline for the thumbnail from the video title.

    The invented track name (ZALIMBA, MALZ…) tells viewers nothing — this adds
    the WHY-click in 2-3 words, matched to the proven title hooks.
    """
    t = (youtube_title or "").lower()
    for needle, tagline in [
        ("need this", "YOU NEED THIS"),
        ("late night", "LATE NIGHT DRIVE"),
        ("different", "HITS DIFFERENT"),
        ("fall in love", "PURE AFRO HOUSE"),
        ("workout", "WORKOUT ENERGY"),
        ("everyone's playing", "EVERYONE'S PLAYING THIS"),
        ("broke my speakers", "BASS OVERLOAD"),
        ("sunrise", "SUNRISE DRIVE"),
        ("believe this drop", "INSANE DROP"),
        ("chills", "PURE CHILLS"),
        ("loud", "PLAY IT LOUD"),
    ]:
        if needle in t:
            return tagline
    return "DEEP AFRO HOUSE"


def _add_tagline(image: Image.Image, tagline: str) -> Image.Image:
    """Overlay the short benefit tagline above the big track name."""
    if not tagline:
        return image
    if THUMBNAIL_TEXT_STYLE == "classic":
        return _add_text_classic(
            image, tagline, y_ratio=0.64, font_size_ratio=0.055, color="#FFFFFF"
        )
    return _add_stylized_text(
        image, tagline, y_ratio=0.64, font_size_ratio=0.055,
        color_top="#FFFFFF", color_bottom="#FFD700", glow=True, divider=False,
    )


def _add_artist_name(image: Image.Image, artist_name: str) -> Image.Image:
    """Overlay the artist name above the track name."""
    if THUMBNAIL_TEXT_STYLE == "classic":
        return _add_text_classic(
            image, artist_name, y_ratio=0.62, font_size_ratio=0.06, color="#FFFFFF"
        )
    return _add_stylized_text(
        image, artist_name, y_ratio=0.62, font_size_ratio=0.06,
        color_top="#FFFFFF", color_bottom="#C0C0C0", glow=False, divider=False,
    )


def _safe_filename(name: str) -> str:
    """Create a filesystem-safe filename from a track name."""
    safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in name)
    return safe.strip().replace(" ", "_")[:50]


def _dall_e_generate(client: OpenAI, prompt: str, size: str) -> Image.Image:
    """Call the OpenAI image API with retry and return a PIL Image.

    OpenAI retired `dall-e-3` (responds with 'model does not exist'). The
    current model is `gpt-image-1`, which returns base64-encoded image bytes
    in `response.data[0].b64_json` instead of a URL.
    """
    import base64

    # gpt-image-1 supports: 1024x1024, 1024x1536, 1536x1024, auto
    size_map = {
        "1792x1024": "1536x1024",
        "1024x1792": "1024x1536",
        "1024x1024": "1024x1024",
    }
    api_size = size_map.get(size, "1024x1024")

    last_err = None
    for attempt in range(1, 5):
        try:
            response = client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                size=api_size,
                n=1,
            )
            data = response.data[0]
            # Prefer base64 (gpt-image-1 default); fall back to URL if present.
            b64 = getattr(data, "b64_json", None)
            if b64:
                log.info("gpt-image-1 image generated, decoding base64...")
                return Image.open(BytesIO(base64.b64decode(b64)))
            url = getattr(data, "url", None)
            if url:
                log.info("gpt-image-1 image generated, downloading...")
                img_response = requests.get(url, timeout=60)
                img_response.raise_for_status()
                return Image.open(BytesIO(img_response.content))
            raise RuntimeError("gpt-image-1 returned neither b64_json nor url")
        except Exception as e:
            last_err = e
            if attempt < 4:
                wait = 2 ** attempt
                log.warning(f"OpenAI image API error (attempt {attempt}/4): {e}")
                log.info(f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"OpenAI image API failed after 4 attempts: {last_err}\n"
                    "Check your OPENAI_API_KEY in .env and internet connection."
                ) from last_err


def _generate_fallback_image(width: int, height: int) -> Image.Image:
    """Generate a gradient-based fallback thumbnail when DALL-E is unavailable.

    Creates a dark professional-looking background with geometric patterns.
    """
    log.info(f"Generating fallback gradient thumbnail ({width}x{height})...")

    # Dark background with a radial gradient
    image = Image.new("RGB", (width, height), "#0a0a0a")
    draw = ImageDraw.Draw(image)

    # Radial gradient from center
    cx, cy = width // 2, height // 2
    max_dist = (cx ** 2 + cy ** 2) ** 0.5

    # Choose random accent colors for variety
    accents = [
        ("#FFD700", "#8B4513"),  # gold + dark brown
        ("#00BFFF", "#001133"),  # electric blue + navy
        ("#FF6B00", "#1a0500"),  # orange + very dark orange
        ("#FF1493", "#1a001a"),  # deep pink + very dark purple
        ("#00FF88", "#001a0d"),  # neon green + dark green
    ]
    bright, dark = random.choice(accents)

    # Draw concentric circles for gradient effect
    for r in range(int(max_dist), 0, -4):
        ratio = r / max_dist
        # Interpolate between accent and dark
        br, bg, bb = int(bright[1:3], 16), int(bright[3:5], 16), int(bright[5:7], 16)
        dr, dg, db = int(dark[1:3], 16), int(dark[3:5], 16), int(dark[5:7], 16)
        cr = int(dr + (br - dr) * (1 - ratio) * 0.3)
        cg = int(dg + (bg - dg) * (1 - ratio) * 0.3)
        cb = int(db + (bb - db) * (1 - ratio) * 0.3)
        color = f"#{cr:02x}{cg:02x}{cb:02x}"
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=color,
        )

    # Add some geometric lines for visual interest
    for _ in range(8):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        opacity = random.randint(20, 60)
        line_color = f"#{opacity:02x}{opacity:02x}{opacity:02x}"
        draw.line([(x1, y1), (x2, y2)], fill=line_color, width=1)

    # Apply slight blur for smoothness
    image = image.filter(ImageFilter.GaussianBlur(radius=2))

    return image


def _save_thumbnail_compressed(image: Image.Image, output_path: Path) -> Path:
    """Save thumbnail as JPEG, compressing to stay under YouTube's 2MB limit."""
    image = image.convert("RGB")
    quality = 95
    while quality >= 50:
        image.save(str(output_path), "JPEG", quality=quality, optimize=True)
        file_size = output_path.stat().st_size
        if file_size <= 2_000_000:
            log.info(f"Thumbnail saved ({file_size // 1024}KB, quality={quality}): {output_path}")
            return output_path
        log.info(f"Thumbnail too large ({file_size // 1024}KB) at quality={quality}, reducing...")
        quality -= 10

    # Last resort: resize to fit
    log.warning("Thumbnail still too large, resizing to 1280x720...")
    image = image.resize((1280, 720), Image.LANCZOS)
    image.save(str(output_path), "JPEG", quality=85, optimize=True)
    log.info(f"Thumbnail saved (resized, {output_path.stat().st_size // 1024}KB): {output_path}")
    return output_path


def generate_thumbnail_and_cover(
    thumbnail_prompt: str,
    track_name: str,
    artist_name: str = "",
    youtube_title: str = "",
) -> tuple[Path, Path]:
    """Generate BOTH YouTube thumbnail and TuneCore cover art from ONE DALL-E call.

    Uses a single 1792x1024 DALL-E generation, then:
    - YouTube thumbnail: full 1792x1024 image with track name overlay
    - TuneCore cover: center-cropped to 1024x1024, upscaled to 1600x1600,
      with artist name + track name overlay

    This saves one DALL-E API call (~$0.04) and halves generation time.

    Args:
        thumbnail_prompt: DALL-E prompt for the image.
        track_name: Track name to overlay.
        artist_name: Artist name for cover art (optional, shown above track name).

    Returns:
        Tuple of (thumbnail_path, cover_path).
    """
    log.info(f"Generating thumbnail + cover art for: {track_name}")
    safe_name = _safe_filename(track_name)

    # Try DALL-E first, fall back to local generation
    try:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY not set")
        client = OpenAI(api_key=OPENAI_API_KEY)
        base_image = _dall_e_generate(client, thumbnail_prompt, "1792x1024")
        log.info("DALL-E image ready — deriving thumbnail + cover from single image")
    except Exception as e:
        log.warning(f"DALL-E generation failed: {e}")
        log.info("Using fallback gradient thumbnail...")
        base_image = _generate_fallback_image(1792, 1024)

    # ── YouTube Thumbnail (1792x1024) ──
    # Tagline (benefit hook) goes ONLY on the YouTube thumbnail — streaming
    # stores (DistroKid/Spotify/Apple) reject covers with any extra text.
    thumb = base_image.copy()
    tagline = _tagline_from_title(youtube_title)
    thumb = _add_tagline(thumb, tagline)
    thumb = _add_track_name(thumb, track_name)
    log.info(f"Thumbnail tagline: {tagline}")
    thumbnail_path = OUTPUT_DIR / f"{safe_name}_thumbnail.jpg"
    _save_thumbnail_compressed(thumb, thumbnail_path)

    # ── TuneCore Cover Art (1600x1600, center-cropped from the same image) ──
    w, h = base_image.size  # 1792x1024
    # Center-crop to the largest square that fits
    crop_size = min(w, h)  # 1024
    left = (w - crop_size) // 2
    top = 0
    cover = base_image.crop((left, top, left + crop_size, top + crop_size))
    # Upscale to 1600x1600 (TuneCore minimum)
    cover = cover.resize((1600, 1600), Image.LANCZOS)
    # Overlay ONLY the track name — no band, glow or divider
    cover = _add_cover_name_only(cover, track_name)

    cover_path = OUTPUT_DIR / f"{safe_name}_cover.jpg"
    cover = cover.convert("RGB")
    cover.save(str(cover_path), "JPEG", quality=95, optimize=True)
    log.info(f"Cover art saved ({cover_path.stat().st_size // 1024}KB): {cover_path}")

    return thumbnail_path, cover_path


def generate_cover_art(
    thumbnail_prompt: str,
    track_name: str,
    artist_name: str = "",
) -> Path:
    """Generate a 1600x1600 square cover art for TuneCore distribution.

    Uses DALL-E 3 at 1024x1024 (square), then upscales to 1600x1600.
    Overlays artist name and track name.
    Falls back to gradient-based generation if DALL-E fails.
    """
    log.info(f"Generating 1600x1600 cover art for TuneCore: {track_name}")
    safe_name = _safe_filename(track_name)

    # TuneCore rejects covers with ANY text other than the title/artist name.
    # Enforce a strict no-text constraint on the DALL-E prompt.
    no_text_rule = (
        " ABSOLUTELY NO TEXT, NO LETTERS, NO WORDS, NO WRITING, NO SIGNAGE,"
        " NO GRAFFITI, NO LOGOS, NO TYPOGRAPHY, NO NUMBERS, NO SYMBOLS,"
        " NO CAPTIONS anywhere in the image. The image must be PURELY visual"
        " with zero written content of any kind."
    )
    cover_prompt = thumbnail_prompt.rstrip('. ') + '.' + no_text_rule

    try:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY not set")
        client = OpenAI(api_key=OPENAI_API_KEY)
        image = _dall_e_generate(client, cover_prompt, "1024x1024")
    except Exception as e:
        log.warning(f"DALL-E cover art failed: {e}")
        log.info("Using fallback gradient cover art...")
        image = _generate_fallback_image(1024, 1024)

    # Upscale to 1600x1600 (TuneCore minimum)
    image = image.resize((1600, 1600), Image.LANCZOS)

    # Overlay ONLY the track name — no band, glow or divider
    image = _add_cover_name_only(image, track_name)

    output_path = OUTPUT_DIR / f"{safe_name}_cover.jpg"
    image = image.convert("RGB")
    image.save(str(output_path), "JPEG", quality=95, optimize=True)
    log.info(f"Cover art saved ({output_path.stat().st_size // 1024}KB): {output_path}")
    return output_path


def generate_thumbnail(thumbnail_prompt: str, track_name: str) -> Path:
    """Generate a thumbnail with the track name using DALL-E 3.

    Falls back to gradient-based generation if DALL-E fails.
    """
    log.info(f"Generating thumbnail for: {track_name}")
    safe_name = _safe_filename(track_name)

    try:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY not set")
        client = OpenAI(api_key=OPENAI_API_KEY)
        image = _dall_e_generate(client, thumbnail_prompt, "1792x1024")
    except Exception as e:
        log.warning(f"DALL-E thumbnail failed: {e}")
        log.info("Using fallback gradient thumbnail...")
        image = _generate_fallback_image(1792, 1024)

    image = _add_track_name(image, track_name)

    output_path = OUTPUT_DIR / f"{safe_name}_thumbnail.jpg"
    return _save_thumbnail_compressed(image, output_path)
