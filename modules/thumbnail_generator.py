import random
import time
from pathlib import Path
import requests
from io import BytesIO
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from config import OPENAI_API_KEY, OUTPUT_DIR
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


def _add_text_with_shadow(
    image: Image.Image,
    text: str,
    y_ratio: float,
    font_size_ratio: float,
    color: str = "#FFD700",
) -> Image.Image:
    """Overlay text with a drop shadow for readability.

    Args:
        image: PIL Image to draw on.
        text: Text to render (will be uppercased).
        y_ratio: Vertical position as ratio of image height (0.0 = top, 1.0 = bottom).
        font_size_ratio: Font size as ratio of image height.
        color: Text color (hex or name).
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size

    font_size = int(height * font_size_ratio)
    font = _get_font(font_size)
    text = text.upper()

    # Measure text
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Scale down font if text is wider than image (with padding)
    max_width = int(width * 0.9)
    if text_w > max_width:
        font_size = int(font_size * max_width / text_w)
        font = _get_font(font_size)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

    # Center horizontally, position vertically by ratio
    x = (width - text_w) // 2
    y = int(height * y_ratio) - text_h // 2

    # Draw black outline for readability (circular outline)
    outline_width = max(3, font_size // 12)
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx * dx + dy * dy <= outline_width * outline_width:
                draw.text((x + dx, y + dy), text, font=font, fill="black")

    # Draw main text
    draw.text((x, y), text, font=font, fill=color)

    return image


def _add_track_name(image: Image.Image, track_name: str) -> Image.Image:
    """Overlay the track name in bold gold text in the lower third."""
    return _add_text_with_shadow(image, track_name, y_ratio=0.78, font_size_ratio=0.12)


def _add_artist_name(image: Image.Image, artist_name: str) -> Image.Image:
    """Overlay the artist name in white text above the track name."""
    return _add_text_with_shadow(
        image, artist_name, y_ratio=0.62, font_size_ratio=0.06, color="#FFFFFF"
    )


def _safe_filename(name: str) -> str:
    """Create a filesystem-safe filename from a track name."""
    safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in name)
    return safe.strip().replace(" ", "_")[:50]


def _dall_e_generate(client: OpenAI, prompt: str, size: str) -> Image.Image:
    """Call DALL-E 3 with retry and return a PIL Image."""
    last_err = None
    for attempt in range(1, 5):
        try:
            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size,
                quality="standard",
                n=1,
            )
            image_url = response.data[0].url
            log.info("DALL-E image generated, downloading...")
            img_response = requests.get(image_url, timeout=60)
            img_response.raise_for_status()
            return Image.open(BytesIO(img_response.content))
        except Exception as e:
            last_err = e
            if attempt < 4:
                wait = 2 ** attempt
                log.warning(f"DALL-E API error (attempt {attempt}/4): {e}")
                log.info(f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"DALL-E API failed after 4 attempts: {last_err}\n"
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
    thumb = base_image.copy()
    thumb = _add_track_name(thumb, track_name)
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
    # Overlay track name only (TuneCore requires cover with song name only)
    cover = _add_track_name(cover, track_name)

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

    try:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY not set")
        client = OpenAI(api_key=OPENAI_API_KEY)
        image = _dall_e_generate(client, thumbnail_prompt, "1024x1024")
    except Exception as e:
        log.warning(f"DALL-E cover art failed: {e}")
        log.info("Using fallback gradient cover art...")
        image = _generate_fallback_image(1024, 1024)

    # Upscale to 1600x1600 (TuneCore minimum)
    image = image.resize((1600, 1600), Image.LANCZOS)

    # Overlay track name only (TuneCore requires cover with song name only)
    image = _add_track_name(image, track_name)

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
