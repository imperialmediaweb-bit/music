import json
import re
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

# ── Fusion genres for the 13:00 slot (Afro House × another genre) ──
FUSION_GENRES = [
    {
        "name": "Afro House × Japanese",
        "secondary": "Japanese",
        "instruments": "koto, shamisen, taiko drums, shakuhachi flute, bamboo percussion",
        "music_style": (
            "Create an EPIC fusion track blending Afro House grooves with traditional Japanese "
            "instrumentation. 122 BPM. Layer organic African percussion (djembe, congas, shakers) "
            "with Japanese koto melodies, shamisen plucks, deep taiko drum hits, and haunting "
            "shakuhachi flute. Build progressive transitions with evolving pads, tribal chants "
            "intertwined with Japanese vocal textures. Massive sub-bass with car bass resonance. "
            "The vibe is mystical, cinematic, and hypnotic — East meets Africa in a deep, "
            "festival-ready fusion. Mastered for warmth, clarity, and sub-bass impact."
        ),
        "thumbnail_style": (
            "A STUNNING fusion artwork: an African tribal mask MERGED with Japanese aesthetic elements. "
            "The mask combines carved African wood textures with Japanese lacquer finish, gold leaf "
            "(kintsugi style), cherry blossom petals floating around it, and samurai armor details. "
            "Background: deep dark with a blood-red rising sun glow behind the mask. "
            "GLOWING EYES with supernatural energy (neon crimson or electric gold). "
            "Mix African tribal patterns with Japanese geometric waves (seigaiha) and cloud motifs. "
            "Dramatic spotlight lighting, volumetric fog, floating cherry blossoms and embers. "
            "Cinematic, vivid, powerful. No text. 4K ultra detailed. Music album cover aesthetic."
        ),
    },
    {
        "name": "Afro House × Greek",
        "secondary": "Greek",
        "instruments": "bouzouki, lyra, santouri, daouli drum, laouto",
        "music_style": (
            "Create an EPIC fusion track blending Afro House grooves with traditional Greek "
            "instrumentation. 122 BPM. Layer organic African percussion (djembe, congas, shakers) "
            "with Greek bouzouki melodies, Cretan lyra, santouri hammered dulcimer, and deep "
            "daouli drum accents. Build progressive transitions with evolving Mediterranean pads, "
            "tribal chants mixed with Greek vocal scales (dromos). Massive sub-bass with car bass. "
            "The vibe is passionate, cinematic, and euphoric — Mediterranean meets Africa in a deep, "
            "festival-ready fusion. Mastered for warmth, clarity, and sub-bass impact."
        ),
        "thumbnail_style": (
            "A STUNNING fusion artwork: an African tribal mask MERGED with ancient Greek aesthetic. "
            "The mask combines carved African wood with white marble texture, golden laurel wreaths, "
            "Greek meander/key patterns, and Ionic column details. "
            "Background: deep dark Aegean blue with golden divine light radiating behind the mask. "
            "GLOWING EYES with supernatural energy (electric blue or golden white glow). "
            "Mix African tribal scarification with Greek geometric patterns and olive branch motifs. "
            "Dramatic spotlight lighting, volumetric fog, floating golden particles and sparks. "
            "Cinematic, vivid, powerful — ancient gods aesthetic. No text. 4K ultra detailed."
        ),
    },
    {
        "name": "Afro House × Latin Folk",
        "secondary": "Latin Folk",
        "instruments": "charango, quena flute, cajón, maracas, pan flute, guitarrón",
        "music_style": (
            "Create an EPIC fusion track blending Afro House grooves with traditional Latin Folk "
            "instrumentation. 122 BPM. Layer organic African percussion (djembe, congas, shakers) "
            "with Andean quena flute, charango strings, deep cajón rhythms, maracas, and "
            "pan flute melodies. Build progressive transitions with evolving pads, tribal chants "
            "intertwined with Latin vocal textures and folkloric harmonies. Massive sub-bass. "
            "The vibe is fiery, cinematic, and passionate — Latin America meets Africa in a deep, "
            "festival-ready fusion. Mastered for warmth, clarity, and sub-bass impact."
        ),
        "thumbnail_style": (
            "A STUNNING fusion artwork: an African tribal mask MERGED with Latin American folk art. "
            "The mask combines carved African wood with colorful Aztec/Mayan mosaic patterns, "
            "turquoise and jade inlays, feathered headdress elements (quetzal feathers), "
            "and pre-Columbian gold ornaments. "
            "Background: deep dark with fiery orange/red/gold gradient glow behind the mask. "
            "GLOWING EYES with supernatural energy (emerald green or fiery orange glow). "
            "Mix African tribal patterns with Aztec geometric designs and sun symbols. "
            "Dramatic spotlight lighting, volumetric smoke, floating embers and golden dust. "
            "Cinematic, vivid, powerful — ancient civilizations collide. No text. 4K ultra detailed."
        ),
    },
]


def _build_fusion_system_prompt(fusion: dict, music_style: str) -> str:
    """Build system prompt for the 13:00 fusion slot."""
    name = fusion["name"]
    secondary = fusion["secondary"]
    instruments = fusion["instruments"]
    genre_lower = name.lower().replace(" ", "").replace("×", "x")

    return f"""You are a creative music producer specializing in GENRE FUSION and a YouTube SEO expert.
Generate a unique {name} fusion track concept. This is a MEGA COMBINATION of Afro House with {secondary} music.

The track style is:
{music_style}

KEY INSTRUMENTS to feature: {instruments}

IMPORTANT NAMING RULE:
- The track_name MUST be 1-2 short, catchy, invented words that blend African and {secondary} vibes.
- They should sound exotic and memorable — a fusion of both cultures.
- CRITICAL: Vary the starting letter EVERY TIME.
- Examples: Sakurai, Mykonari, Zenturi, Andeko, Folkama, Quetzani, Bouzouma.

CRITICAL: The youtube_title MUST mention "MEGA COMBINATION" or "MEGA FUSION" and reference both genres.
- Example formats:
  - TRACKNAME 🔥 MEGA COMBINATION Afro House × {secondary} | Mindblowing Fusion | #afrohouse
  - TRACKNAME 🔥 MEGA FUSION: Afro House Meets {secondary} | {instruments.split(',')[0].strip()} + Tribal Drums | #afrohouse
  - TRACKNAME 🔥 Afro House × {secondary} MEGA MIX | Insane {instruments.split(',')[0].strip()} Fusion | #afrohouse

Everything (youtube_title, youtube_description, hashtags, youtube_tags, tiktok_caption) MUST be in English.

Return ONLY valid JSON with these exact fields:

{{
  "track_name": "1-2 invented words blending African + {secondary} vibes",
  "mood": "emotional mood/vibe — pick something UNIQUE (e.g. euphoric, mystical, volcanic, celestial)",
  "description": "2-3 sentences about this FUSION track — mention both genres and the instruments",
  "music_prompt": "detailed prompt for AI music generation — describe the fusion of instruments, rhythm, bass. Must blend Afro House with {secondary}.",
  "hashtags": ["#afrohouse", "#{secondary.lower().replace(' ', '')}", "#fusion", "#megamix", "#tribalhouse", "#newmusic2026", "#deephouse", "#musicfusion", "#worldmusic", "#electronicmusic", "#djmix", "#afrotribal"],
  "youtube_title": "MUST include 'MEGA COMBINATION' or 'MEGA FUSION' + both genre names. Fire emoji. Max 100 chars. End with #afrohouse. Make it EXTREMELY clickable and viral.",
  "youtube_description": "Write a LONG (25+ lines) description. FIRST mention this is a MEGA COMBINATION of Afro House × {secondary}. Describe the unique instruments ({instruments}). Use keywords: afro house 2026, {secondary.lower()} music, fusion, mega combination, tribal beats, deep bass. Include use cases, CTA, and keyword cloud. All keywords should say 2026 NOT 2025. Contact: imperialmediaweb@gmail.com",
  "youtube_tags": ["afro house", "{secondary.lower()} music", "afro house {secondary.lower()} fusion", "mega combination", "mega fusion", "afro house 2026", "tribal house", "deep house", "{instruments.split(',')[0].strip().lower()}", "world music fusion", "new music 2026", "best afro house 2026", "african music", "{secondary.lower()} fusion", "dj mix 2026"],
  "tiktok_caption": "MAX 150 chars. Viral hook about this INSANE fusion + hashtags #fyp #afrohouse #{secondary.lower().replace(' ', '')} #fusion #megamix",
  "thumbnail_prompt": "Generate a UNIQUE fusion artwork prompt combining African tribal aesthetics with {secondary} visual elements. The image must SCREAM 'fusion of two cultures'. GLOWING EYES, HIGH CONTRAST, dramatic lighting. No text. 4K."
}}"""



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
  "youtube_title": "Create a UNIQUE, ULTRA-ATTRACTIVE YouTube title designed to MAXIMIZE click-through rate (CTR) and YouTube recommendations. RANDOMLY pick ONE of these proven VIRAL formats:\\n\\nFORMATS (pick ONE, never repeat):\\n- TRACKNAME 🔥 The Most ADDICTIVE {genre} Track of 2026 | [Mood] Extended Mix | {genre_hashtag}\\n- TRACKNAME 🔥 This {genre} Track Will POSSESS Your Soul | {genre_hashtag}\\n- TRACKNAME 🔥 FORBIDDEN {genre} Gem | Once You Hear It You Can't Stop | {genre_hashtag}\\n- TRACKNAME 🔥 [Mood] {genre} Mix That Will HAUNT You | {genre_hashtag}\\n- TRACKNAME 🔥 The {genre} Masterpiece Everyone Is Talking About | {genre_hashtag}\\n- TRACKNAME 🔥 GODLY {genre} Mix | Tribal Beats From Another Dimension | {genre_hashtag}\\n- TRACKNAME 🔥 WARNING: This {genre} Track Is DANGEROUSLY Addictive | {genre_hashtag}\\n- TRACKNAME 🔥 LEGENDARY African Energy | {genre} Extended 2026 | {genre_hashtag}\\n- TRACKNAME 🔥 The {genre} Drop That SHOOK The Internet | {genre_hashtag}\\n- TRACKNAME 🔥 SACRED Tribal Journey | Deep {genre} You MUST Hear | {genre_hashtag}\\n- TRACKNAME 🔥 Best {genre} Track 2026 | UNREAL Tribal Power | {genre_hashtag}\\n- TRACKNAME 🔥 PRIMAL {genre} Energy | Your New Obsession | {genre_hashtag}\\n- TRACKNAME 🔥 {genre} Gem So Good It Should Be ILLEGAL | {genre_hashtag}\\n- TRACKNAME 🔥 EPIC {genre} Extended Mix | Feels Like A SPIRITUAL Experience | {genre_hashtag}\\n- TRACKNAME 🔥 INSANE {genre} Drop | Tribal Beats That Hit DIFFERENT | {genre_hashtag}\\n- TRACKNAME 🔥 MASSIVE {genre} Mix 2026 | Underground Gem | {genre_hashtag}\\n\\nSEO KEYWORD RULES:\\n1. ALWAYS include the genre name '{genre}' in the title (critical for search ranking)\\n2. Include at least ONE power word: ADDICTIVE, LEGENDARY, FORBIDDEN, GODLY, SACRED, PRIMAL, EPIC, INSANE, MASSIVE, UNREAL\\n3. Use EXTREME curiosity gaps and emotional triggers to MAXIMIZE clicks\\n4. Front-load the most important keywords (first 50 chars matter most for search)\\n5. Make titles feel URGENT and UNMISSABLE — the viewer should feel they NEED to click\\n6. Use 2026 when mentioning year\\n\\nPower words: ADDICTIVE, LEGENDARY, FORBIDDEN, GODLY, SACRED, PRIMAL, EPIC, INSANE, MASSIVE, UNREAL, DANGEROUS, HYPNOTIC, POSSESSED, SPIRITUAL, OTHERWORLDLY, DEVASTATING.\\n\\nRules: track name UPPERCASE, fire emoji after name, end with {genre_hashtag}, max 100 chars. Do NOT include duration. EVERY title MUST be COMPLETELY different.",
  "youtube_description": "Write a LONG (25+ lines) YouTube description FULLY OPTIMIZED for YouTube SEO and algorithm recommendations. The description is CRITICAL for YouTube search ranking and suggested videos.\\n\\nSTRUCTURE (follow this order):\\n\\n1. FIRST 2 LINES (most important — shown in search results before 'Show more'):\\n   - Include the EXACT track name and genre '{genre}' in the first sentence\\n   - Use high-search keywords: {genre}, deep house, tribal house, African music, mix, new music 2026\\n   - Make it compelling enough to click 'Show more'\\n\\n2. KEYWORD-RICH BODY (5-8 lines):\\n   - Describe the track's sound, instruments, energy, and atmosphere\\n   - Naturally weave in SEARCH KEYWORDS: {genre}, tribal beats, deep bass, African drums, underground music, DJ mix, electronic music, dance music\\n   - Mention related genres: deep house, tribal house, organic house, melodic house\\n   - Each sentence should contain at least one searchable keyword\\n\\n3. USE CASES with keywords (3-4 lines):\\n   - 'Perfect for: [keyword-rich list]' — gym workout music, driving music, DJ sets, festival music, meditation, study music, car bass music, late night vibes\\n   - This helps YouTube match your video to DIFFERENT search queries\\n\\n4. CALL TO ACTION (2-3 lines):\\n   - Ask viewers to LIKE, SUBSCRIBE, and turn on NOTIFICATIONS\\n   - Ask them to COMMENT their favorite part\\n   - Ask them to SHARE with friends who love {genre}\\n   - Engagement signals (likes, comments, shares) directly boost YouTube recommendations\\n\\n5. KEYWORD CLOUD (5-8 lines):\\n   - List related search terms that people actually search on YouTube:\\n   - '{genre} mix 2026', 'best {genre} tracks', 'deep tribal house', 'African house music',\\n     'underground {genre}', '{genre} DJ set', 'new {genre} music', 'tribal drums',\\n     '{genre} car bass', 'deep house mix', 'organic house', 'afro tribal'\\n   - Format as a clean list, one per line\\n\\n6. CONTACT: imperialmediaweb@gmail.com\\n\\nIMPORTANT RULES:\\n- Do NOT include hashtags (#) in the description (they get added separately)\\n- EVERY sentence should be keyword-rich but still read naturally\\n- VARY the structure, wording, and keywords each time — no two descriptions should be similar\\n- Use line breaks and spacing for readability",
  "youtube_tags": ["Generate 25-30 YouTube tags OPTIMIZED for search discovery and algorithm recommendations. Tags are how YouTube understands what your video is about and who to show it to.\\n\\nINCLUDE THESE TAG CATEGORIES (mix all together):\\n\\n1. EXACT MATCH genre tags (highest priority):\\n   '{genre}', '{genre} music', '{genre} mix', '{genre} 2026', 'new {genre}', 'best {genre}'\\n\\n2. RELATED genre tags (expands reach to related audiences):\\n   'deep house', 'tribal house', 'organic house', 'melodic house', 'african house music', 'afro tribal', 'ethnic house', 'progressive house'\\n\\n3. MOOD/VIBE tags (matches user search intent):\\n   'deep bass music', 'tribal drums', 'african drums', 'hypnotic beats', 'car bass music', 'festival music', 'underground music'\\n\\n4. USE CASE tags (captures different search queries):\\n   'gym music', 'driving music', 'DJ mix', 'party music', 'workout music', 'study beats', 'night drive music'\\n\\n5. TRENDING/DISCOVERY tags:\\n   'new music 2026', 'music mix 2026', 'best music 2026', 'trending music', 'viral music'\\n\\n6. TRACK-SPECIFIC tags: include the track name as a tag\\n\\nRULES: Each tag max 100 chars, total under 500 chars. Mix short (1-2 word) and long-tail (3-4 word) tags. NO hashtag symbols."],
  "tiktok_caption": "Write a VIRAL TikTok caption optimized for TikTok's For You Page (FYP) algorithm. MAX 150 chars.\\n\\nFORMULA: [Viral hook] + [3-5 strategic hashtags]\\n\\nVIRAL HOOKS (pick one, vary each time):\\n- 'This beat hits different 🔥'\\n- 'Wait for the drop... 🫠'\\n- 'Name a better {genre} track, I'll wait 🎧'\\n- 'POV: you found the perfect {genre} gem 💎'\\n- 'This track is INSANE 🤯'\\n- 'When the tribal drums kick in 🥁🔥'\\n- 'Why is nobody talking about this?!'\\n- 'Put this on repeat 🔁🔥'\\n\\nHASHTAG STRATEGY (mix niche + broad for maximum reach):\\n- ALWAYS include: #fyp #foryou (algorithm boost)\\n- Genre: #{genre_lower} #afrohouse #deephouse #tribalhouse\\n- Trending: #newmusic #viralmusic #musicdiscovery\\n- Niche: #undergroundmusic #africanbeats #tribalbeats\\n\\nPick 3-5 hashtags that fit within the 150 char limit. Always include #fyp.",
  "thumbnail_prompt": "Generate a UNIQUE image prompt for an authentic African tribal mask OPTIMIZED for YouTube thumbnail click-through rate. HIGH CONTRAST and BOLD COLORS are critical for thumbnails — they must POP on small screens and stand out in YouTube's suggested videos sidebar.\\n\\nEACH mask must be from a DIFFERENT African tribe/tradition — rotate between: Yoruba (Nigeria), Dogon (Mali), Fang (Gabon), Punu (Gabon), Dan (Ivory Coast), Kuba (Congo), Chokwe (Angola), Makonde (Tanzania), Baule (Ivory Coast), Songye (Congo), Luba (Congo), Bamana (Mali).\\n\\nTHUMBNAIL CTR OPTIMIZATION RULES:\\n1. SUPER HIGH CONTRAST: dark black/deep navy background with BRIGHT glowing elements (neon gold, electric blue, fiery orange, vivid red)\\n2. DRAMATIC LIGHTING: spotlight or rim lighting that makes the mask POP against the dark background\\n3. GLOWING EYES on the mask — eyes that glow with intense supernatural energy (most clicked element on thumbnails)\\n4. BOLD COLOR ACCENTS: at least one vivid neon/glowing color that catches attention at small sizes\\n5. DEPTH and SMOKE: volumetric fog, embers, sparks, or mystical particles floating around the mask\\n6. CENTERED COMPOSITION: mask takes up 60-70% of the frame for maximum visual impact at small sizes\\n\\nDescribe: specific mask style, materials (carved wood, cowrie shells, raffia, brass, beads), ritual purpose, and the dramatic lighting/glow effects. No text. 4K ultra detailed. Must be COMPLETELY different from any previous mask."
}}"""


def generate_fusion_concept(track_name: str = "") -> MusicConcept:
    """Generate a fusion concept for the 13:00 slot (Afro House × another genre).

    Randomly picks one of: Japanese, Greek, or Latin Folk as the secondary genre.
    """
    import random
    fusion = random.choice(FUSION_GENRES)
    log.info(f"Fusion slot: {fusion['name']} (instruments: {fusion['instruments']})")

    music_style = fusion["music_style"]
    thumbnail_style = fusion["thumbnail_style"]

    client = OpenAI(api_key=OPENAI_API_KEY)
    system_prompt = _build_fusion_system_prompt(fusion, music_style)

    user_msg = (
        f"Generate a fresh, original {fusion['name']} fusion track concept. "
        f"This is a MEGA COMBINATION of Afro House with {fusion['secondary']} music, "
        f"featuring instruments like {fusion['instruments']}. "
        "The track name should blend African and "
        f"{fusion['secondary']} vibes. "
        "The title MUST say MEGA COMBINATION or MEGA FUSION. "
        "Everything (title, description, tags) must be in English. "
        "All year references must be 2026, NOT 2025."
    )
    if track_name:
        user_msg = (
            f"Generate a {fusion['name']} fusion concept for a track called '{track_name}'. "
            f"Use '{track_name}' as the track_name. "
            "The title MUST say MEGA COMBINATION or MEGA FUSION. "
            "Everything must be in English. All year references must be 2026."
        )

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
                wait = 2 ** attempt
                log.warning(f"OpenAI API error (attempt {attempt}/4): {e}")
                log.info(f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"OpenAI API failed after 4 attempts: {last_err}"
                ) from last_err

    raw = response.choices[0].message.content
    data = json.loads(raw)
    if track_name:
        data["track_name"] = track_name
    final_name = data.get("track_name", "Tribal Pulse")
    final_name = re.sub(r'\s*#\S+', '', final_name).strip()
    log.info(f"Generated fusion concept: {final_name} ({fusion['name']})")

    music_prompt = data.get("music_prompt", "")
    if not music_prompt:
        music_prompt = music_style

    ai_tags = data.get("youtube_tags", [])
    seen = set()
    final_tags = []
    for tag in ai_tags:
        tag_lower = tag.lower().strip()
        if tag_lower and tag_lower not in seen:
            seen.add(tag_lower)
            final_tags.append(tag)

    ai_thumbnail = data.get("thumbnail_prompt", "")
    final_thumbnail = ai_thumbnail if ai_thumbnail else thumbnail_style

    return MusicConcept(
        track_name=final_name,
        genre=fusion["name"],
        mood=data.get("mood", "euphoric, mystical, powerful"),
        description=data.get("description", f"A {fusion['name']} fusion track called {final_name}"),
        music_prompt=music_prompt,
        hashtags=data.get("hashtags", ["afrohouse", "fusion", "megamix", "newmusic"]),
        thumbnail_prompt=final_thumbnail,
        youtube_title=data.get("youtube_title", f"{final_name} - {fusion['name']} MEGA FUSION"),
        youtube_description=data.get("youtube_description", f"{final_name} - A {fusion['name']} fusion track."),
        youtube_tags=final_tags,
        tiktok_caption=data.get("tiktok_caption", f"{final_name} #afrohouse #fusion #fyp"),
    )


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
    # Strip hashtags that AI sometimes appends (e.g. "Gaharé #Afrohouse" → "Gaharé")
    final_name = re.sub(r'\s*#\S+', '', final_name).strip()
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
