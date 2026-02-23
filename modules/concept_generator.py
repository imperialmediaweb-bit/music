import json
import random
from dataclasses import dataclass, field
from openai import OpenAI
from config import OPENAI_API_KEY, MUSIC_GENRE_POOL
from utils.logger import log


@dataclass
class MusicConcept:
    track_name: str
    genre: str
    mood: str
    description: str
    lyrics: str
    hashtags: list[str]
    thumbnail_prompt: str
    youtube_title: str
    youtube_description: str
    tiktok_caption: str


SYSTEM_PROMPT = """You are a creative music producer and content strategist.
Generate a unique music track concept. Return ONLY valid JSON with these exact fields:

{
  "track_name": "creative, catchy track name",
  "genre": "music genre",
  "mood": "emotional mood/vibe",
  "description": "2-3 sentence description of the track",
  "lyrics": "4-8 lines of lyrics or instrumental description",
  "hashtags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "thumbnail_prompt": "detailed DALL-E prompt for album cover art - vivid, artistic, no text",
  "youtube_title": "catchy YouTube title with emoji (max 100 chars)",
  "youtube_description": "YouTube description with track info, mood, genre (3-5 sentences)",
  "tiktok_caption": "short TikTok caption with hashtags (max 150 chars)"
}"""


def generate_concept() -> MusicConcept:
    genre = random.choice(MUSIC_GENRE_POOL)
    log.info(f"Generating music concept for genre: {genre}")

    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Generate a {genre} music track concept. Make it fresh and original.",
            },
        ],
        temperature=1.0,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    data = json.loads(raw)
    track_name = data.get("track_name", "Untitled Track")
    genre_val = data.get("genre", genre)
    log.info(f"Generated concept: {track_name} ({genre_val})")

    return MusicConcept(
        track_name=track_name,
        genre=genre_val,
        mood=data.get("mood", "chill"),
        description=data.get("description", f"A {genre_val} track called {track_name}"),
        lyrics=data.get("lyrics", ""),
        hashtags=data.get("hashtags", [genre_val, "music", "newmusic"]),
        thumbnail_prompt=data.get("thumbnail_prompt", f"abstract artistic album cover art, {genre_val} music aesthetic, vibrant colors, no text"),
        youtube_title=data.get("youtube_title", f"{track_name} - {genre_val}"),
        youtube_description=data.get("youtube_description", f"{track_name} - a {genre_val} track."),
        tiktok_caption=data.get("tiktok_caption", f"{track_name} #{genre_val} #music"),
    )
