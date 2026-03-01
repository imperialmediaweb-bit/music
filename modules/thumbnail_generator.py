import time
from pathlib import Path
import requests
from io import BytesIO
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
from config import OPENAI_API_KEY, OUTPUT_DIR
from utils.logger import log


def _add_track_name(image: Image.Image, track_name: str) -> Image.Image:
    """Overlay the track name in bold text on the thumbnail."""
    draw = ImageDraw.Draw(image)
    width, height = image.size

    # Try to use a bold font, fall back to default
    font_size = int(height * 0.12)
    font = None
    for font_name in ["Impact", "Arial Bold", "arialbd.ttf", "DejaVuSans-Bold.ttf"]:
        try:
            font = ImageFont.truetype(font_name, font_size)
            break
        except (OSError, IOError):
            continue
    if font is None:
        font = ImageFont.load_default()

    text = track_name.upper()

    # Measure text
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Center horizontally, place in lower third
    x = (width - text_w) // 2
    y = int(height * 0.75)

    # Draw black outline for readability
    outline_width = max(3, font_size // 15)
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx * dx + dy * dy <= outline_width * outline_width:
                draw.text((x + dx, y + dy), text, font=font, fill="black")

    # Draw gold text
    draw.text((x, y), text, font=font, fill="#FFD700")

    return image


def generate_cover_art(thumbnail_prompt: str, track_name: str) -> Path:
    """Generate a 1600x1600 square cover art for TuneCore distribution.

    Uses DALL-E 3 at 1024x1024 (square), then upscales to 1600x1600.
    Overlays the track name in bold gold text.
    """
    log.info(f"Generating 1600x1600 cover art for TuneCore: {track_name}")

    client = OpenAI(api_key=OPENAI_API_KEY)

    last_err = None
    for attempt in range(1, 5):
        try:
            response = client.images.generate(
                model="dall-e-3",
                prompt=thumbnail_prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )
            break
        except Exception as e:
            last_err = e
            if attempt < 4:
                wait = 2 ** attempt
                log.warning(f"DALL-E API error (attempt {attempt}/4): {e}")
                log.info(f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"DALL-E API failed after 4 attempts: {last_err}"
                ) from last_err

    image_url = response.data[0].url
    log.info("Cover art generated, downloading...")

    img_response = requests.get(image_url, timeout=60)
    img_response.raise_for_status()

    image = Image.open(BytesIO(img_response.content))

    # Upscale to 1600x1600 (TuneCore minimum)
    image = image.resize((1600, 1600), Image.LANCZOS)

    # Overlay track name only (same name as on TuneCore platform)
    image = _add_track_name(image, track_name)

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in track_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50]
    output_path = OUTPUT_DIR / f"{safe_name}_cover.jpg"

    image = image.convert("RGB")
    image.save(str(output_path), "JPEG", quality=95, optimize=True)
    log.info(f"Cover art saved ({output_path.stat().st_size // 1024}KB): {output_path}")
    return output_path


def generate_thumbnail(thumbnail_prompt: str, track_name: str) -> Path:
    """Generate an African mask thumbnail with the track name using DALL-E 3.

    1. DALL-E generates the African mask background
    2. Pillow overlays the track name in bold gold text
    """
    log.info(f"Generating African mask thumbnail for: {track_name}")

    client = OpenAI(api_key=OPENAI_API_KEY)

    # Retry with exponential backoff for transient connection errors
    last_err = None
    for attempt in range(1, 5):
        try:
            response = client.images.generate(
                model="dall-e-3",
                prompt=thumbnail_prompt,
                size="1792x1024",
                quality="standard",
                n=1,
            )
            break
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

    image_url = response.data[0].url
    log.info("Thumbnail generated, downloading...")

    img_response = requests.get(image_url, timeout=60)
    img_response.raise_for_status()

    # Open image and overlay track name
    image = Image.open(BytesIO(img_response.content))
    image = _add_track_name(image, track_name)

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in track_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50]
    output_path = OUTPUT_DIR / f"{safe_name}_thumbnail.jpg"

    # Save as JPEG with compression to stay under YouTube's 2MB limit.
    # Start at quality 95 and reduce until file is under 2MB.
    image = image.convert("RGB")  # JPEG doesn't support alpha
    quality = 95
    while quality >= 50:
        image.save(str(output_path), "JPEG", quality=quality, optimize=True)
        file_size = output_path.stat().st_size
        if file_size <= 2_000_000:  # 2MB with safety margin
            log.info(f"Thumbnail saved ({file_size // 1024}KB, quality={quality}): {output_path}")
            return output_path
        log.info(f"Thumbnail too large ({file_size // 1024}KB) at quality={quality}, reducing...")
        quality -= 10

    # Last resort: resize the image to fit
    log.warning("Thumbnail still too large, resizing to 1280x720...")
    image = image.resize((1280, 720), Image.LANCZOS)
    image.save(str(output_path), "JPEG", quality=85, optimize=True)
    log.info(f"Thumbnail saved (resized, {output_path.stat().st_size // 1024}KB): {output_path}")
    return output_path
