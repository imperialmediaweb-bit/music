import json
import time
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

SYSTEM_PROMPT = """You are a creative Afro House music producer and YouTube SEO expert.
Generate a unique Afro House track concept. The track style is always:
""" + AFRO_HOUSE_STYLE + """

IMPORTANT NAMING RULE:
- The track_name MUST be invented African-sounding words with NO real meaning.
- Examples: "Zanu", "Maku", "Piku", "Dakora", "Mbawu", "Tikala", "Nyoru", "Zafiki", "Obandu", "Kwelu"
- Use 1-2 short, punchy, exotic-sounding words. They should sound African/tribal but NOT be real words.
- Do NOT use English words for the track name.

CRITICAL: Every track MUST have a COMPLETELY DIFFERENT youtube_title and youtube_description.
- Do NOT reuse phrases from previous tracks.
- Vary the structure, wording, and style of descriptions each time.
- Use different adjectives, metaphors, and sentence patterns.

Everything else (youtube_title, youtube_description, hashtags, youtube_tags, tiktok_caption) MUST be in English.

Return ONLY valid JSON with these exact fields:

{
  "track_name": "1-2 invented African-sounding words, no real meaning (e.g. Zanu, Maku, Tikala)",
  "mood": "emotional mood/vibe — pick something UNIQUE each time (e.g. ritualistic, primal, euphoric, hypnotic, volcanic, celestial, nocturnal, cinematic, shamanic, trance-like)",
  "description": "2-3 sentence vivid description of the track's atmosphere and energy (in English)",
  "music_prompt": "detailed prompt for AI music generation - describe instruments, rhythm, bass, mood, tempo 122 BPM, Afro House style with car bass",
  "hashtags": ["afrohouse", "afrohousemusic", "deepafrohouse", "tribalafrohouse", "organicafrohouse", "primalafrohouse", "afrohouseritual", "undergroundafrohouse", "afrohousemix", "warehousevibes", "ritualgroove", "deephouse", "tribalhouse", "afrohouse2025", "extendedmix"],
  "youtube_title": "Create a CLICKBAIT-style YouTube title that makes people NEED to click. Format: TRACKNAME 🔥 [Clickbait Hook] | [Element] #afrohouse. Use power words like: INSANE, MASSIVE, ULTIMATE, LEGENDARY, MIND-BLOWING, EUPHORIC, GODLIKE, UNSTOPPABLE, HEAVIEST, DARKEST. Example titles: 'KAMUZI 🔥 The HEAVIEST Afro House Drop You Will Ever Hear | Insane Tribal Bass #afrohouse' or 'DAKORA 🔥 This Beat Will POSSESS Your Soul | Dark Tribal Afro House Ritual #afrohouse'. Rules: track name UPPERCASE, 🔥 emoji, end with #afrohouse, max 100 chars. Do NOT include duration. EVERY title must be DIFFERENT and attention-grabbing.",
  "youtube_description": "Write a LONG (20+ lines) SEO-optimized YouTube description. VARY the structure each time — do NOT copy a template. Include:\n\n1. Opening hook: compelling first 2 lines about THIS specific track (YouTube shows these in search results)\n2. Detailed description of the track's sound, instruments, and atmosphere (3-5 lines)\n3. What this track is perfect for: driving, gym, meditation, DJ sets, festivals, etc (use bullet points or emojis, vary the style)\n4. A unique closing statement or call to action\n5. Contact: 📩 imperialmediaweb@gmail.com\n\nIMPORTANT: Do NOT include hashtags in the description. Do NOT use the exact same structure every time — be creative with formatting.",
  "youtube_tags": ["afro house", "afro house music", "deep afro house", "tribal afro house", "organic afro house", "afro house mix", "underground afro house", "afro house ritual", "deep house", "tribal house", "warehouse vibes", "afro house 2025", "extended mix", "car bass", "afro house DJ set", "afro house playlist", "deep tribal drums", "african drums music", "bass boosted", "car music bass boosted", "afro house new 2025", "best afro house", "afro house workout", "afro house drive", "tribal percussion"],
  "tiktok_caption": "short TikTok caption in English with hashtags including #afrohouse #afrohousemusic #deepafrohouse #tribalhouse (max 150 chars)"
}"""


def generate_concept(track_name: str = "") -> MusicConcept:
    """Generate an Afro House track concept via OpenAI.

    Args:
        track_name: If provided, forces this name instead of letting AI pick one.
    """
    log.info("Generating Afro House music concept...")

    client = OpenAI(api_key=OPENAI_API_KEY)

    user_msg = (
        "Generate a fresh, original Afro House track concept. "
        "The track name MUST be invented African-sounding nonsense words "
        "(like Zanu, Maku, Piku, Dakora, Mbawu). NOT English words. "
        "Everything else (title, description, tags) must be in English."
    )
    if track_name:
        user_msg = (
            f"Generate an Afro House track concept for a track called '{track_name}'. "
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
                    {"role": "system", "content": SYSTEM_PROMPT},
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

    # Build thumbnail prompt: African mask (text is added by Pillow, not DALL-E)
    thumbnail_prompt = (
        "A dramatic, high-detail African tribal mask centered on a dark, smoky background. "
        "The mask is ornate with gold, bronze, and deep red tribal patterns, glowing edges, "
        "and mystical energy radiating from it. No text or letters on the image. "
        "The overall style is cinematic, vivid, dark, and powerful. "
        "Afro House music album cover aesthetic. 4K quality, ultra detailed."
    )

    # Build music generation prompt
    music_prompt = data.get("music_prompt", "")
    if not music_prompt:
        music_prompt = (
            f"{AFRO_HOUSE_STYLE}\n"
            f"Track name: {final_name}\n"
            f"Mood: {data.get('mood', 'ritualistic, primal, powerful, transcendent')}"
        )

    # Merge mandatory SEO tags with AI-generated tags (deduplicated).
    # Keep this list SHORT and DIVERSE — too many similar "afro house X" tags
    # triggers YouTube's spam detection ("invalid video keywords" error).
    MANDATORY_TAGS = [
        "afro house", "deep house", "tribal house", "african drums",
        "car bass music", "bass boosted", "warehouse music",
        "tribal percussion", "extended mix",
    ]
    ai_tags = data.get("youtube_tags", [])
    seen = set()
    final_tags = []
    for tag in MANDATORY_TAGS + ai_tags:
        tag_lower = tag.lower().strip()
        if tag_lower and tag_lower not in seen:
            seen.add(tag_lower)
            final_tags.append(tag)

    return MusicConcept(
        track_name=final_name,
        genre="Afro House",
        mood=data.get("mood", "ritualistic, primal, powerful, transcendent"),
        description=data.get("description", f"A deep, hypnotic Afro House track called {final_name}"),
        music_prompt=music_prompt,
        hashtags=data.get("hashtags", ["afrohouse", "afrohousemusic", "deepafrohouse", "tribalafrohouse", "organicafrohouse", "primalafrohouse", "afrohouseritual", "undergroundafrohouse", "afrohousemix", "warehousevibes", "ritualgroove", "deephouse", "tribalhouse", "afrohouse2025", "extendedmix"]),
        thumbnail_prompt=thumbnail_prompt,
        youtube_title=data.get("youtube_title", f"{final_name} - Afro House"),
        youtube_description=data.get("youtube_description", f"{final_name} - A deep Afro House track."),
        youtube_tags=final_tags,
        tiktok_caption=data.get("tiktok_caption", f"{final_name} #afrohouse #tribal #deepbass"),
    )
