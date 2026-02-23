from pathlib import Path
import requests
from openai import OpenAI
from config import OPENAI_API_KEY, OUTPUT_DIR
from utils.logger import log


def generate_thumbnail(thumbnail_prompt: str, track_name: str) -> Path:
    """Generate an African mask thumbnail with the track name using DALL-E 3."""
    log.info(f"Generating African mask thumbnail for: {track_name}")

    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.images.generate(
        model="dall-e-3",
        prompt=thumbnail_prompt,
        size="1792x1024",
        quality="hd",
        n=1,
    )

    image_url = response.data[0].url
    log.info("Thumbnail generated, downloading...")

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in track_name)
    safe_name = safe_name.strip().replace(" ", "_")[:50]
    output_path = OUTPUT_DIR / f"{safe_name}_thumbnail.png"

    img_response = requests.get(image_url, timeout=60)
    img_response.raise_for_status()

    with open(output_path, "wb") as f:
        f.write(img_response.content)

    log.info(f"Thumbnail saved to: {output_path}")
    return output_path
