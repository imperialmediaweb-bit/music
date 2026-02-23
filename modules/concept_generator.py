import json
from dataclasses import dataclass
from openai import OpenAI
from config import OPENAI_API_KEY
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


AFRO_HOUSE_STYLE = (
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

SYSTEM_PROMPT = """You are a creative Afro House music producer and content strategist.
Generate a unique Afro House track concept. The track style is always:
""" + AFRO_HOUSE_STYLE + """

Return ONLY valid JSON with these exact fields:

{
  "track_name": "creative, catchy, vivid Afro House track name (2-4 words, powerful and memorable)",
  "mood": "emotional mood/vibe (e.g. ritualistic, primal, powerful, transcendent)",
  "description": "2-3 sentence vivid description of the track's atmosphere and energy",
  "music_prompt": "detailed prompt for AI music generation - describe instruments, rhythm, bass, mood, tempo 122 BPM, Afro House style with car bass",
  "hashtags": ["afrohouse", "tribalbass", "deephouse", + 7 more relevant tags],
  "youtube_title": "catchy YouTube title with emoji, include track name and Afro House (max 100 chars)",
  "youtube_description": "full YouTube description: track name, genre (Afro House), mood, style description, call to subscribe, 3-5 sentences",
  "youtube_tags": ["afro house", "deep house", "tribal", "car bass", + 10 more relevant SEO tags],
  "tiktok_caption": "short TikTok caption with hashtags (max 150 chars)"
}"""


def generate_concept() -> MusicConcept:
    log.info("Generating Afro House music concept...")

    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Generate a fresh, original Afro House track concept. "
                    "The name should be vivid, powerful, and memorable. "
                    "Think ritualistic, primal, transcendent vibes."
                ),
            },
        ],
        temperature=1.0,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    data = json.loads(raw)
    track_name = data.get("track_name", "Tribal Pulse")
    log.info(f"Generated concept: {track_name}")

    # Build thumbnail prompt: African mask with track name
    thumbnail_prompt = (
        f"A dramatic, high-detail African tribal mask centered on a dark, smoky background. "
        f"The mask is ornate with gold, bronze, and deep red tribal patterns, glowing edges, "
        f"and mystical energy radiating from it. The text '{track_name}' is displayed in bold, "
        f"modern metallic gold font across the image. The overall style is cinematic, vivid, "
        f"dark, and powerful. Afro House music album cover aesthetic. 4K quality, ultra detailed."
    )

    # Build music generation prompt
    music_prompt = data.get("music_prompt", "")
    if not music_prompt:
        music_prompt = (
            f"{AFRO_HOUSE_STYLE}\n"
            f"Track name: {track_name}\n"
            f"Mood: {data.get('mood', 'ritualistic, primal, powerful, transcendent')}"
        )

    return MusicConcept(
        track_name=track_name,
        genre="Afro House",
        mood=data.get("mood", "ritualistic, primal, powerful, transcendent"),
        description=data.get("description", f"A deep, hypnotic Afro House track called {track_name}"),
        music_prompt=music_prompt,
        hashtags=data.get("hashtags", ["afrohouse", "tribalbass", "deephouse", "carbass", "music"]),
        thumbnail_prompt=thumbnail_prompt,
        youtube_title=data.get("youtube_title", f"{track_name} - Afro House"),
        youtube_description=data.get("youtube_description", f"{track_name} - A deep Afro House track."),
        youtube_tags=data.get("youtube_tags", ["afro house", "deep house", "tribal", "car bass"]),
        tiktok_caption=data.get("tiktok_caption", f"{track_name} #afrohouse #tribal #deepbass"),
    )
