import json
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
    "A dramatic, high-detail AUTHENTIC African tribal mask centered on a deep dark background. "
    "Each mask must be COMPLETELY UNIQUE — vary the tribe/region inspiration: "
    "Yoruba, Dogon, Fang, Punu, Dan, Kuba, Chokwe, Makonde, Baule, Songye, Luba, Bamana. "
    "Use authentic patterns, materials and colors from real African art traditions: "
    "carved wood with natural patina, cowrie shells, raffia, brass ornaments, scarification marks, "
    "geometric tribal patterns, ritual paint in ochre/indigo/kaolin white. "
    "CRITICAL FOR THUMBNAILS: The mask must have GLOWING EYES with intense supernatural energy "
    "(neon gold, electric blue, or fiery orange glow). Use EXTREME HIGH CONTRAST — dark background "
    "with BRIGHT vivid glowing elements that POP. Add dramatic rim lighting, volumetric smoke, "
    "floating embers and mystical particles. The mask should take up 60-70% of the frame. "
    "No text or letters on the image. "
    "The overall style is cinematic, vivid, dark, and powerful — like a sacred artifact photographed "
    "in dramatic spotlight lighting. Afro House music album cover aesthetic. 4K quality, ultra detailed."
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
- CRITICAL: Vary the starting letter EVERY TIME. Use ALL letters of the alphabet — A, B, D, G, K, M, N, O, S, T, etc. Do NOT always start with Z.
- Examples of good diverse names: Bakari, Djenné, Kisumu, Makossa, Ngoma, Safiri, Tabora, Owari, Gajani, Lumba, Echoro, Haruna, Fikiri.

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
  "youtube_title": "Create a UNIQUE, algorithm-optimized YouTube title designed to MAXIMIZE click-through rate (CTR) and YouTube recommendations. RANDOMLY pick ONE of these proven HIGH-CTR formats:\\n\\nFORMATS (pick ONE, never repeat):\\n- TRACKNAME 🔥 Mindblowing {genre} Gem | [Vibe] Extended Mix | {genre_hashtag}\\n- TRACKNAME 🔥 This {genre} Track Will Give You Chills | {genre_hashtag}\\n- TRACKNAME 🔥 Hidden {genre} Gem | [Mood] Extended | {genre_hashtag}\\n- TRACKNAME 🔥 [Mood] {genre} Mix You NEED To Hear | {genre_hashtag}\\n- TRACKNAME 🔥 Underground {genre} Gem | Mindblowing Tribal Beats | {genre_hashtag}\\n- TRACKNAME 🔥 Extended {genre} Mix | [Mood] Deep Tribal | {genre_hashtag}\\n- TRACKNAME 🔥 The {genre} Gem That Broke The Internet | {genre_hashtag}\\n- TRACKNAME 🔥 Mindblowing African Energy | {genre} Extended | {genre_hashtag}\\n- TRACKNAME 🔥 Rare {genre} Gem | This Will Blow Your Mind | {genre_hashtag}\\n- TRACKNAME 🔥 [Mood] Tribal Journey | Deep {genre} Extended | {genre_hashtag}\\n- TRACKNAME 🔥 Best {genre} Gem [Year] | Mindblowing Mix | {genre_hashtag}\\n- TRACKNAME 🔥 Extended Deep {genre} | Hidden Gem | {genre_hashtag}\\n- TRACKNAME 🔥 {genre} Gem You Won't Believe Exists | {genre_hashtag}\\n- TRACKNAME 🔥 Insane {genre} Extended Mix | [Mood] Vibes | {genre_hashtag}\\n\\nSEO KEYWORD RULES:\\n1. ALWAYS include the genre name '{genre}' in the title (critical for search ranking)\\n2. Include at least ONE of: 'gem', 'mindblowing', 'extended', 'mix', 'deep', 'tribal'\\n3. Use curiosity gaps and emotional triggers to MAXIMIZE click-through rate\\n4. Front-load the most important keywords (first 50 chars matter most for search)\\n5. Words like 'gem', 'extended mix', 'mindblowing' are PROVEN to attract clicks in music\\n\\nPower words to MIX IN: GEM, MINDBLOWING, EXTENDED, HIDDEN, INSANE, ADDICTIVE, LEGENDARY, FORBIDDEN, HYPNOTIC, MASSIVE, EPIC, RARE, PRIMAL, SACRED, UNREAL, GODLY.\\n\\nRules: track name UPPERCASE, fire emoji after name, end with {genre_hashtag}, max 100 chars. Do NOT include duration. EVERY title MUST be COMPLETELY different.",
  "youtube_description": "Write a LONG (25+ lines) YouTube description FULLY OPTIMIZED for YouTube SEO and algorithm recommendations. The description is CRITICAL for YouTube search ranking and suggested videos.\\n\\nSTRUCTURE (follow this order):\\n\\n1. FIRST 2 LINES (most important — shown in search results before 'Show more'):\\n   - Include the EXACT track name and genre '{genre}' in the first sentence\\n   - Use high-search keywords: {genre}, deep house, tribal house, African music, mix, new music 2025\\n   - Make it compelling enough to click 'Show more'\\n\\n2. KEYWORD-RICH BODY (5-8 lines):\\n   - Describe the track's sound, instruments, energy, and atmosphere\\n   - Naturally weave in SEARCH KEYWORDS: {genre}, tribal beats, deep bass, African drums, underground music, DJ mix, electronic music, dance music\\n   - Mention related genres: deep house, tribal house, organic house, melodic house\\n   - Each sentence should contain at least one searchable keyword\\n\\n3. USE CASES with keywords (3-4 lines):\\n   - 'Perfect for: [keyword-rich list]' — gym workout music, driving music, DJ sets, festival music, meditation, study music, car bass music, late night vibes\\n   - This helps YouTube match your video to DIFFERENT search queries\\n\\n4. CALL TO ACTION (2-3 lines):\\n   - Ask viewers to LIKE, SUBSCRIBE, and turn on NOTIFICATIONS\\n   - Ask them to COMMENT their favorite part\\n   - Ask them to SHARE with friends who love {genre}\\n   - Engagement signals (likes, comments, shares) directly boost YouTube recommendations\\n\\n5. KEYWORD CLOUD (5-8 lines):\\n   - List related search terms that people actually search on YouTube:\\n   - '{genre} mix 2025', 'best {genre} tracks', 'deep tribal house', 'African house music',\\n     'underground {genre}', '{genre} DJ set', 'new {genre} music', 'tribal drums',\\n     '{genre} car bass', 'deep house mix', 'organic house', 'afro tribal'\\n   - Format as a clean list, one per line\\n\\n6. CONTACT: imperialmediaweb@gmail.com\\n\\nIMPORTANT RULES:\\n- Do NOT include hashtags (#) in the description (they get added separately)\\n- EVERY sentence should be keyword-rich but still read naturally\\n- VARY the structure, wording, and keywords each time — no two descriptions should be similar\\n- Use line breaks and spacing for readability",
  "youtube_tags": ["Generate 25-30 YouTube tags OPTIMIZED for search discovery and algorithm recommendations. Tags are how YouTube understands what your video is about and who to show it to.\\n\\nINCLUDE THESE TAG CATEGORIES (mix all together):\\n\\n1. EXACT MATCH genre tags (highest priority):\\n   '{genre}', '{genre} music', '{genre} mix', '{genre} 2025', 'new {genre}', 'best {genre}'\\n\\n2. RELATED genre tags (expands reach to related audiences):\\n   'deep house', 'tribal house', 'organic house', 'melodic house', 'african house music', 'afro tribal', 'ethnic house', 'progressive house'\\n\\n3. MOOD/VIBE tags (matches user search intent):\\n   'deep bass music', 'tribal drums', 'african drums', 'hypnotic beats', 'car bass music', 'festival music', 'underground music'\\n\\n4. USE CASE tags (captures different search queries):\\n   'gym music', 'driving music', 'DJ mix', 'party music', 'workout music', 'study beats', 'night drive music'\\n\\n5. TRENDING/DISCOVERY tags:\\n   'new music 2025', 'music mix 2025', 'best music 2025', 'trending music', 'viral music'\\n\\n6. TRACK-SPECIFIC tags: include the track name as a tag\\n\\nRULES: Each tag max 100 chars, total under 500 chars. Mix short (1-2 word) and long-tail (3-4 word) tags. NO hashtag symbols."],
  "tiktok_caption": "Write a VIRAL TikTok caption optimized for TikTok's For You Page (FYP) algorithm. MAX 150 chars.\\n\\nFORMULA: [Viral hook] + [3-5 strategic hashtags]\\n\\nVIRAL HOOKS (pick one, vary each time):\\n- 'This beat hits different 🔥'\\n- 'Wait for the drop... 🫠'\\n- 'Name a better {genre} track, I'll wait 🎧'\\n- 'POV: you found the perfect {genre} gem 💎'\\n- 'This track is INSANE 🤯'\\n- 'When the tribal drums kick in 🥁🔥'\\n- 'Why is nobody talking about this?!'\\n- 'Put this on repeat 🔁🔥'\\n\\nHASHTAG STRATEGY (mix niche + broad for maximum reach):\\n- ALWAYS include: #fyp #foryou (algorithm boost)\\n- Genre: #{genre_lower} #afrohouse #deephouse #tribalhouse\\n- Trending: #newmusic #viralmusic #musicdiscovery\\n- Niche: #undergroundmusic #africanbeats #tribalbeats\\n\\nPick 3-5 hashtags that fit within the 150 char limit. Always include #fyp.",
  "thumbnail_prompt": "Generate a UNIQUE image prompt for an authentic African tribal mask OPTIMIZED for YouTube thumbnail click-through rate. HIGH CONTRAST and BOLD COLORS are critical for thumbnails — they must POP on small screens and stand out in YouTube's suggested videos sidebar.\\n\\nEACH mask must be from a DIFFERENT African tribe/tradition — rotate between: Yoruba (Nigeria), Dogon (Mali), Fang (Gabon), Punu (Gabon), Dan (Ivory Coast), Kuba (Congo), Chokwe (Angola), Makonde (Tanzania), Baule (Ivory Coast), Songye (Congo), Luba (Congo), Bamana (Mali).\\n\\nTHUMBNAIL CTR OPTIMIZATION RULES:\\n1. SUPER HIGH CONTRAST: dark black/deep navy background with BRIGHT glowing elements (neon gold, electric blue, fiery orange, vivid red)\\n2. DRAMATIC LIGHTING: spotlight or rim lighting that makes the mask POP against the dark background\\n3. GLOWING EYES on the mask — eyes that glow with intense supernatural energy (most clicked element on thumbnails)\\n4. BOLD COLOR ACCENTS: at least one vivid neon/glowing color that catches attention at small sizes\\n5. DEPTH and SMOKE: volumetric fog, embers, sparks, or mystical particles floating around the mask\\n6. CENTERED COMPOSITION: mask takes up 60-70% of the frame for maximum visual impact at small sizes\\n\\nDescribe: specific mask style, materials (carved wood, cowrie shells, raffia, brass, beads), ritual purpose, and the dramatic lighting/glow effects. No text. 4K ultra detailed. Must be COMPLETELY different from any previous mask."
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

    client = OpenAI(api_key=OPENAI_API_KEY)

    system_prompt = _build_system_prompt(genre, music_style)

    user_msg = (
        f"Generate a fresh, original {genre} track concept. "
        "The track name MUST be invented catchy African-sounding words — NOT common English words. "
        "IMPORTANT: Start the name with a DIFFERENT letter each time — do NOT always use Z. Vary across the whole alphabet. "
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

    # Use AI-generated thumbnail prompt if available, otherwise fall back to default
    ai_thumbnail = data.get("thumbnail_prompt", "")
    final_thumbnail = ai_thumbnail if ai_thumbnail else thumbnail_style

    return MusicConcept(
        track_name=final_name,
        genre=genre,
        mood=data.get("mood", "energetic, powerful, transcendent"),
        description=data.get("description", f"A {genre} track called {final_name}"),
        music_prompt=music_prompt,
        hashtags=data.get("hashtags", [genre_lower, f"{genre_lower}music", "music", "newmusic"]),
        thumbnail_prompt=final_thumbnail,
        youtube_title=data.get("youtube_title", f"{final_name} - {genre}"),
        youtube_description=data.get("youtube_description", f"{final_name} - A {genre} track."),
        youtube_tags=final_tags,
        tiktok_caption=data.get("tiktok_caption", f"{final_name} #{genre_lower} #music #newmusic"),
    )
