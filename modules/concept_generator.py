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

SYSTEM_PROMPT = """You are a creative Afro House music producer and content strategist.
Generate a unique Afro House track concept. The track style is always:
""" + AFRO_HOUSE_STYLE + """

IMPORTANT NAMING RULE:
- The track_name MUST be invented African-sounding words with NO real meaning.
- Examples: "Zanu", "Maku", "Piku", "Dakora", "Mbawu", "Tikala", "Nyoru", "Zafiki", "Obandu", "Kwelu"
- Use 1-2 short, punchy, exotic-sounding words. They should sound African/tribal but NOT be real words.
- Do NOT use English words for the track name.

Everything else (youtube_title, youtube_description, hashtags, youtube_tags, tiktok_caption) MUST be in English.

Return ONLY valid JSON with these exact fields:

{
  "track_name": "1-2 invented African-sounding words, no real meaning (e.g. Zanu, Maku, Tikala)",
  "mood": "emotional mood/vibe (e.g. ritualistic, primal, powerful, transcendent)",
  "description": "2-3 sentence vivid description of the track's atmosphere and energy (in English)",
  "music_prompt": "detailed prompt for AI music generation - describe instruments, rhythm, bass, mood, tempo 122 BPM, Afro House style with car bass",
  "hashtags": ["afrohouse", "afrohousemusic", "deepafrohouse", "tribalafrohouse", "organicafrohouse", "primalafrohouse", "afrohouseritual", "undergroundafrohouse", "afrohousemix", "warehousevibes", "ritualgroove", "deephouse", "tribalhouse", "afrohouse2025", "extendedmix"],
  "youtube_title": "MUST follow this EXACT format: TRACKNAME 🔥 [Descriptive Afro House Subtitle] | [Deep Tribal/Underground Element] #afrohouse — Example: KAMUZI 🔥 Primal Afro House Ritual | Deep Tribal Drums & Hypnotic Underground Groove #afrohouse — Rules: track name UPPERCASE, include 🔥 emoji, end with #afrohouse, max 100 chars. Do NOT include duration (it will be added automatically).",
  "youtube_description": "Write a LONG detailed YouTube description following this EXACT structure (at least 20 lines):\n\nLine 1: [TRACK_NAME] is a deep Afro House ritual built around [describe: raw tribal percussion, rolling basslines, hypnotic rhythms etc].\n\nLine 2-3: This [X]-minute extended mix blends:\n• primal African drums\n• organic percussion layers\n• deep rolling bass\n• ritual fire atmosphere\n• immersive underground energy\n(Customize the bullet points to match the track mood)\n\nNext paragraph: No commercial breaks. No pop drops. No shortcuts.\n\nNext paragraph with fire emojis:\nJust pure Afro House flow designed for:\n🔥 warehouse sessions\n🔥 night drives\n🔥 deep focus listening\n🔥 underground DJ vibes\n🔥 long-form YouTube journeys\n\nNext paragraph: [TRACK_NAME] carries ancestral rhythm energy with a modern Afro House pulse — steady, hypnotic, and powerful from start to finish.\n\nFinal line: Turn it up. Let the drums take control. Enter the ritual.\n\nContact line: 📩 For collaborations & promo: imperialmediaweb@gmail.com",
  "youtube_tags": ["afro house", "afro house music", "deep afro house", "tribal afro house", "organic afro house", "afro house mix", "underground afro house", "afro house ritual", "deep house", "tribal house", "warehouse vibes", "afro house 2025", "extended mix", "car bass", "afro house DJ set"],
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

    # Merge mandatory SEO tags with AI-generated tags (deduplicated)
    MANDATORY_TAGS = [
        "afro house", "afro house music", "deep afro house", "tribal afro house",
        "organic afro house", "afro house mix", "underground afro house",
        "afro house ritual", "deep house", "tribal house", "afro house 2025",
        "car bass music", "warehouse music",
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
