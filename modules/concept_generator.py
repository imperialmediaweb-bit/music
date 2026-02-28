import json
import os
import time
from dataclasses import dataclass
from openai import OpenAI
from config import OPENAI_API_KEY, MUSIC_GENRE, MUSIC_STYLE_PROMPT, THUMBNAIL_STYLE_PROMPT
from utils.logger import log


@dataclass
class MusicConcept:
    track_name: str
    genre: str
    mood: str
    description: str
    music_prompt: str
    hashtags: list[str]
    thumbnail_prompt: str
    youtube_title: str
    youtube_description: str
    youtube_tags: list[str]
    tiktok_caption: str


# Default style prompts per genre (used when no custom prompt is set)
DEFAULT_AFRO_HOUSE_STYLE = (
    "Create a progressive Afro House track infused with heavy car bass and deep, "
    "psychedelic tribal energy. The tempo is 122 BPM, blending organic percussion "
    "(congas, shakers, djembe, bongos) with massive analog low-end — the kind of "
    "bass that moves both air and soul. Layer psychedelic textures, evolving "
    "atmospheric pads, and subtle vocal tribal chants that echo through wide stereo "
    "space. Introduce dark, evolving synth arps and progressive transitions that "
    "rise gradually toward a cinematic, festival-style drop. The groove should feel "
    "spiritual yet raw, balancing Afro rhythms with deep car bass resonance, perfect "
    "for big sound systems and open-air sets. The overall sound is deep, hypnotic, "
    "and cinematic, mastered for warmth, clarity, and sub-bass impact."
)

DEFAULT_THUMBNAIL_PROMPT = (
    "A dramatic, high-detail African tribal mask centered on a dark, smoky background. "
    "The mask is ornate with gold, bronze, and deep red tribal patterns, glowing edges, "
    "and mystical energy radiating from it. No text or letters on the image. "
    "The overall style is cinematic, vivid, dark, and powerful. "
    "Afro House music album cover aesthetic. 4K quality, ultra detailed."
)


def _build_system_prompt(genre: str, music_style: str) -> str:
    """Build the system prompt dynamically based on genre and style."""
    genre_lower = genre.lower().replace(" ", "")
    genre_hashtag = f"#{genre_lower}"

    return f"""You are a creative {genre} music producer and YouTube SEO expert.
Generate a unique {genre} track concept. The track style is:
{music_style}

IMPORTANT NAMING RULE:
- The track_name MUST be 1-2 short, catchy, invented words that fit the {genre} vibe.
- They should sound exotic and memorable but NOT be common English words.
- Do NOT use generic or overused names.

CRITICAL: Every track MUST have a COMPLETELY DIFFERENT youtube_title and youtube_description.
- Do NOT reuse phrases from previous tracks.
- Vary the structure, wording, and style of descriptions each time.
- Use different adjectives, metaphors, and sentence patterns.

Everything else (youtube_title, youtube_description, hashtags, youtube_tags, tiktok_caption) MUST be in English.

Return ONLY valid JSON with these exact fields:

{{
  "track_name": "1-2 invented catchy words that fit the {genre} vibe",
  "mood": "emotional mood/vibe — pick something UNIQUE each time (e.g. euphoric, hypnotic, volcanic, celestial, nocturnal, cinematic, dreamy, aggressive, ethereal, melancholic)",
  "description": "2-3 sentence vivid description of the track's atmosphere and energy (in English)",
  "music_prompt": "detailed prompt for AI music generation - describe instruments, rhythm, bass, mood, style. Must match the {genre} genre.",
  "hashtags": ["relevant hashtags for {genre} music - include genre-specific and general music hashtags, 10-15 total"],
  "youtube_title": "Create a CLICKBAIT-style YouTube title that makes people NEED to click. Format: TRACKNAME fire_emoji [Clickbait Hook] | [Element] {genre_hashtag}. Use power words like: INSANE, MASSIVE, ULTIMATE, LEGENDARY, MIND-BLOWING, EUPHORIC, GODLIKE, UNSTOPPABLE, HEAVIEST, DARKEST. Rules: track name UPPERCASE, fire emoji, end with {genre_hashtag}, max 100 chars. Do NOT include duration. EVERY title must be DIFFERENT and attention-grabbing.",
  "youtube_description": "Write a LONG (20+ lines) SEO-optimized YouTube description. VARY the structure each time. Include:\\n\\n1. Opening hook: compelling first 2 lines about THIS specific track\\n2. Detailed description of the track's sound, instruments, and atmosphere (3-5 lines)\\n3. What this track is perfect for: driving, gym, meditation, DJ sets, festivals, etc\\n4. A unique closing statement or call to action\\n5. Contact: imperialmediaweb@gmail.com\\n\\nIMPORTANT: Do NOT include hashtags in the description. Be creative with formatting.",
  "youtube_tags": ["relevant YouTube tags for {genre} music - include genre variations, mood tags, and general music discovery tags, 15-25 total"],
  "tiktok_caption": "short TikTok caption in English with relevant hashtags for {genre} (max 150 chars)"
}}"""


def generate_concept(track_name: str = "", genre: str = "",
                     music_style: str = "", thumbnail_style: str = "") -> MusicConcept:
    """Generate a music track concept via OpenAI.

    Args:
        track_name: If provided, forces this name instead of letting AI pick one.
        genre: Music genre (e.g. "Afro House", "Lo-Fi", "Trap"). Falls back to config.
        music_style: Custom music style prompt. Falls back to config or default.
        thumbnail_style: Custom thumbnail prompt. Falls back to config or default.
    """
    genre = genre or MUSIC_GENRE or "Afro House"
    music_style = music_style or MUSIC_STYLE_PROMPT or DEFAULT_AFRO_HOUSE_STYLE
    thumbnail_style = thumbnail_style or THUMBNAIL_STYLE_PROMPT or DEFAULT_THUMBNAIL_PROMPT

    log.info(f"Generating {genre} music concept...")

    # Read fresh from env (GUI's save_settings updates os.environ via load_dotenv)
    api_key = os.environ.get("OPENAI_API_KEY", "") or OPENAI_API_KEY
    client = OpenAI(api_key=api_key)

    system_prompt = _build_system_prompt(genre, music_style)

    user_msg = (
        f"Generate a fresh, original {genre} track concept. "
        "The track name MUST be invented catchy words — NOT common English words. "
        "Everything else (title, description, tags) must be in English."
    )
    if track_name:
        user_msg = (
            f"Generate a {genre} track concept for a track called '{track_name}'. "
            f"Use '{track_name}' as the track_name. "
            "Everything (title, description, tags) must be in English."
        )

    # Retry with exponential backoff for transient connection errors
    last_err = None
    for attempt in range(1, 5):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                temperature=1.0,
                response_format={"type": "json_object"},
            )
            break
        except Exception as e:
            last_err = e
            if attempt < 4:
                wait = 2 ** attempt  # 2s, 4s, 8s
                log.warning(f"OpenAI API error (attempt {attempt}/4): {e}")
                log.info(f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"OpenAI API failed after 4 attempts: {last_err}\n"
                    "Check your OPENAI_API_KEY in .env and internet connection."
                ) from last_err

    raw = response.choices[0].message.content
    data = json.loads(raw)
    # Force track_name if provided (don't trust AI to follow instructions 100%)
    if track_name:
        data["track_name"] = track_name
    final_name = data.get("track_name", "Tribal Pulse")
    log.info(f"Generated concept: {final_name}")

    # Build music generation prompt
    music_prompt = data.get("music_prompt", "")
    if not music_prompt:
        music_prompt = (
            f"{music_style}\n"
            f"Track name: {final_name}\n"
            f"Mood: {data.get('mood', 'energetic, powerful, transcendent')}"
        )

    # Deduplicate tags
    ai_tags = data.get("youtube_tags", [])
    seen = set()
    final_tags = []
    for tag in ai_tags:
        tag_lower = tag.lower().strip()
        if tag_lower and tag_lower not in seen:
            seen.add(tag_lower)
            final_tags.append(tag)

    genre_lower = genre.lower().replace(" ", "")

    return MusicConcept(
        track_name=final_name,
        genre=genre,
        mood=data.get("mood", "energetic, powerful, transcendent"),
        description=data.get("description", f"A {genre} track called {final_name}"),
        music_prompt=music_prompt,
        hashtags=data.get("hashtags", [genre_lower, f"{genre_lower}music", "music", "newmusic"]),
        thumbnail_prompt=thumbnail_style,
        youtube_title=data.get("youtube_title", f"{final_name} - {genre}"),
        youtube_description=data.get("youtube_description", f"{final_name} - A {genre} track."),
        youtube_tags=final_tags,
        tiktok_caption=data.get("tiktok_caption", f"{final_name} #{genre_lower} #music #newmusic"),
    )
