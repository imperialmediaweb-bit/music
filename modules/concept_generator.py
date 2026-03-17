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
    # ── ASIA ──
    {
        "name": "Afro House × Japanese",
        "secondary": "Japanese",
        "instruments": "koto, shamisen, taiko drums, shakuhachi flute, bamboo percussion",
        "music_style": (
            "Create an EPIC fusion track blending Afro House grooves with traditional Japanese "
            "instrumentation. 122 BPM. Layer organic African percussion (djembe, congas, shakers) "
            "with Japanese koto melodies, shamisen plucks, deep taiko drum hits, and haunting "
            "shakuhachi flute. Massive sub-bass with car bass resonance. "
            "The vibe is mystical, cinematic, and hypnotic — East meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion artwork: an African tribal mask MERGED with Japanese aesthetic. "
            "Carved African wood with Japanese lacquer finish, gold leaf (kintsugi style), "
            "cherry blossom petals floating, samurai armor details. "
            "Background: deep dark with blood-red rising sun glow. "
            "GLOWING EYES (neon crimson or electric gold). Japanese waves + African tribal patterns. "
            "Dramatic lighting, volumetric fog, cherry blossoms and embers. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Chinese",
        "secondary": "Chinese",
        "instruments": "erhu, guzheng, pipa, dizi flute, Chinese gongs, yangqin",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Chinese instrumentation. "
            "122 BPM. Layer African percussion (djembe, congas) with erhu melodies, guzheng arpeggios, "
            "pipa plucks, dizi flute, and deep Chinese gong hits. Progressive transitions with "
            "pentatonic scales, tribal chants intertwined with Chinese vocal textures. Massive sub-bass. "
            "The vibe is ancient, powerful, and mystical — the Silk Road meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Chinese imperial aesthetic. "
            "Carved wood with red lacquer, golden dragon motifs, jade inlays, imperial crown details. "
            "Background: deep dark with golden imperial dragon silhouette glowing. "
            "GLOWING EYES (jade green or imperial gold). Chinese cloud patterns + African scarification. "
            "Dramatic lighting, volumetric red smoke, floating golden particles. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Indian",
        "secondary": "Indian",
        "instruments": "sitar, tabla, tanpura, bansuri flute, sarangi, mridangam",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Indian instrumentation. "
            "122 BPM. Layer African percussion (djembe, congas) with sitar melodies, tabla rhythms, "
            "tanpura drone, bansuri flute, and sarangi bowing. Build progressive ragas over "
            "tribal chants. Massive sub-bass with car bass. "
            "The vibe is transcendent, spiritual, and hypnotic — Bollywood meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Indian aesthetic. "
            "Carved wood with golden mandala patterns, jewel-encrusted third eye, "
            "henna-style geometric designs, peacock feather accents. "
            "Background: deep dark with vibrant saffron/magenta divine glow. "
            "GLOWING EYES (electric saffron or deep violet). Mandala + tribal patterns. "
            "Dramatic lighting, incense smoke effects, floating marigold petals. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Korean",
        "secondary": "Korean",
        "instruments": "gayageum, haegeum, daegeum flute, janggu drum, kkwaenggwari gong",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Korean instrumentation. "
            "122 BPM. Layer African percussion with gayageum plucks, haegeum bowing, daegeum flute, "
            "janggu drum patterns, and kkwaenggwari metallic accents. Progressive transitions with "
            "Korean pansori vocal textures over tribal chants. Massive sub-bass. "
            "The vibe is elegant, powerful, and dynamic — K-tradition meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Korean royal aesthetic. "
            "Carved wood with mother-of-pearl inlay (najeonchilgi), celadon green accents, "
            "hanbok silk patterns, royal crown (gat) details. "
            "Background: deep dark with luminous celadon green and gold glow. "
            "GLOWING EYES (electric turquoise or pale gold). Korean geometric + African tribal. "
            "Dramatic lighting, floating silk ribbons and sparks. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Arabian",
        "secondary": "Arabian",
        "instruments": "oud, qanun, ney flute, darbuka, riq tambourine, rabab",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Arabian instrumentation. "
            "122 BPM. Layer African percussion with oud melodies, qanun arpeggios, haunting ney flute, "
            "darbuka rhythms, and riq accents. Build progressive maqam scales over tribal chants. "
            "Massive sub-bass with desert wind atmospherics. "
            "The vibe is exotic, cinematic, and mesmerizing — Arabia meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Arabian aesthetic. "
            "Carved wood with golden arabesque patterns, crescent moon ornaments, "
            "turquoise mosaic tiles, jeweled details. "
            "Background: deep dark desert night with golden crescent moon glow. "
            "GLOWING EYES (electric turquoise or molten gold). Arabesque + tribal patterns. "
            "Dramatic lighting, golden sand particles, starlit smoke. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Turkish",
        "secondary": "Turkish",
        "instruments": "baglama/saz, kemençe, zurna, davul drum, kanun, kudüm",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Turkish instrumentation. "
            "122 BPM. Layer African percussion with baglama/saz melodies, kemençe bowing, "
            "zurna wind, davul drum power, and kanun arpeggios. Ottoman-scale progressions "
            "mixed with tribal chants. Massive sub-bass. "
            "The vibe is fiery, imperial, and hypnotic — Ottoman Empire meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Ottoman Turkish aesthetic. "
            "Carved wood with Iznik tile patterns (blue/white), tulip motifs, "
            "Ottoman calligraphy-inspired designs, jeweled turban accents. "
            "Background: deep dark with cobalt blue and ruby red glow. "
            "GLOWING EYES (electric cobalt or ruby red). Turkish geometric + African tribal. "
            "Dramatic lighting, floating tile fragments and embers. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Persian",
        "secondary": "Persian",
        "instruments": "tar, setar, santur, kamancheh, tombak, ney",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Persian instrumentation. "
            "122 BPM. Layer African percussion with tar melodies, setar plucks, santur hammered "
            "dulcimer, kamancheh bowing, and tombak hand drum. Persian dastgah modes over "
            "tribal rhythms. Massive sub-bass. "
            "The vibe is poetic, ancient, and mystical — Persia meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Persian aesthetic. "
            "Carved wood with Persian miniature art patterns, lapis lazuli and gold inlay, "
            "cypress tree motifs, peacock-inspired details. "
            "Background: deep dark with deep lapis blue and gold divine glow. "
            "GLOWING EYES (lapis blue or burnished gold). Persian floral + African tribal. "
            "Dramatic lighting, floating rose petals and golden dust. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Vietnamese",
        "secondary": "Vietnamese",
        "instruments": "đàn tranh, đàn bầu, sáo trúc flute, đàn nguyệt, trống drum",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Vietnamese instrumentation. "
            "122 BPM. Layer African percussion with đàn tranh zither, đàn bầu monochord, "
            "sáo trúc bamboo flute, and đàn nguyệt moon lute. Pentatonic melodies over "
            "tribal rhythms. Massive sub-bass. "
            "The vibe is delicate yet powerful, ethereal — Southeast Asia meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Vietnamese aesthetic. "
            "Carved wood with lacquer art, golden lotus motifs, conical hat silhouette, "
            "dragon patterns in red and gold. "
            "Background: deep dark with emerald green and gold glow. "
            "GLOWING EYES (emerald or golden). Vietnamese dragon + African tribal patterns. "
            "Dramatic lighting, floating lotus petals and lantern light. No text. 4K."
        ),
    },
    # ── EUROPE ──
    {
        "name": "Afro House × Greek",
        "secondary": "Greek",
        "instruments": "bouzouki, lyra, santouri, daouli drum, laouto",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Greek instrumentation. "
            "122 BPM. Layer African percussion with bouzouki melodies, Cretan lyra, "
            "santouri hammered dulcimer, and daouli drum accents. Mediterranean pads, "
            "tribal chants mixed with Greek dromos scales. Massive sub-bass. "
            "The vibe is passionate, euphoric — Mediterranean meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with ancient Greek aesthetic. "
            "Carved wood with white marble texture, golden laurel wreaths, "
            "Greek meander/key patterns, Ionic column details. "
            "Background: deep dark Aegean blue with golden divine light. "
            "GLOWING EYES (electric blue or golden white). Greek geometric + African tribal. "
            "Dramatic lighting, floating golden particles. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Irish Celtic",
        "secondary": "Irish Celtic",
        "instruments": "fiddle (violin), uilleann pipes, bodhrán drum, tin whistle, Celtic harp",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Irish Celtic instrumentation. "
            "122 BPM. Layer African percussion with fiddle melodies, uilleann pipes, bodhrán drum, "
            "tin whistle, and Celtic harp arpeggios. Build reels and jigs over tribal grooves. "
            "Massive sub-bass with mystical Celtic atmosphere. "
            "The vibe is wild, enchanting, and euphoric — Celtic magic meets African fire."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Celtic aesthetic. "
            "Carved wood with Celtic knotwork patterns, emerald green accents, "
            "silver torques, druidic oak leaf motifs. "
            "Background: deep dark misty forest with emerald green magical glow. "
            "GLOWING EYES (electric emerald or silver white). Celtic spirals + African tribal. "
            "Dramatic lighting, mystical fog, floating embers and fireflies. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Spanish Flamenco",
        "secondary": "Spanish Flamenco",
        "instruments": "flamenco guitar, cajón, palmas (handclaps), castanets, violin",
        "music_style": (
            "Create an EPIC fusion blending Afro House with Spanish Flamenco instrumentation. "
            "122 BPM. Layer African percussion with passionate flamenco guitar rasgueados, "
            "cajón rhythms, palmas handclaps, castanets, and soulful violin. "
            "Build dramatic flamenco compás over tribal grooves. Massive sub-bass. "
            "The vibe is fiery, passionate, and raw — Andalusia meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Spanish Flamenco aesthetic. "
            "Carved wood with red and black lace patterns, golden fan motifs, "
            "bull silhouette, flamenco rose details. "
            "Background: deep dark with passionate crimson red and gold glow. "
            "GLOWING EYES (fiery red or electric gold). Moorish + African tribal patterns. "
            "Dramatic lighting, floating rose petals and sparks. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Romanian Folk",
        "secondary": "Romanian Folk",
        "instruments": "nai (pan flute), cobza, țambal, fluier, violin, taragot",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Romanian Folk instrumentation. "
            "122 BPM. Layer African percussion with nai pan flute melodies, cobza plucks, "
            "țambal hammered dulcimer, fluier shepherd's flute, and soulful violin. "
            "Doina-style melancholic passages over tribal grooves. Massive sub-bass. "
            "The vibe is haunting, mystical, and soulful — Carpathian mountains meet Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Romanian folk aesthetic. "
            "Carved wood with traditional Romanian embroidery patterns (ie motifs), "
            "red/white/blue cross-stitch, Brâncuși-inspired geometric carvings. "
            "Background: deep dark Carpathian night with mystic blue and red glow. "
            "GLOWING EYES (electric blue or fiery red). Romanian geometric + African tribal. "
            "Dramatic lighting, floating snowflakes and mountain mist. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Balkan",
        "secondary": "Balkan",
        "instruments": "accordion, clarinet, trumpet, tapan drum, gadulka, kaval flute",
        "music_style": (
            "Create an EPIC fusion blending Afro House with Balkan brass and folk instrumentation. "
            "122 BPM. Layer African percussion with Balkan brass (trumpet, clarinet), accordion, "
            "tapan drum power, gadulka bowing, and kaval flute. Irregular Balkan rhythms (7/8, 9/8) "
            "fused with tribal grooves. Massive sub-bass. "
            "The vibe is wild, celebratory, and chaotic — Balkan wedding meets African festival."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Balkan folk aesthetic. "
            "Carved wood with Balkan embroidery, brass instrument motifs, "
            "colorful woven textile patterns, Ottoman-influenced details. "
            "Background: deep dark with warm copper and fiery orange glow. "
            "GLOWING EYES (electric copper or warm gold). Balkan geometric + African tribal. "
            "Dramatic lighting, floating confetti and brass sparks. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Russian",
        "secondary": "Russian",
        "instruments": "balalaika, domra, bayan accordion, gusli, zhaleika",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Russian instrumentation. "
            "122 BPM. Layer African percussion with balalaika tremolo, domra melodies, "
            "bayan accordion chords, gusli arpeggios. Russian folk scales over tribal grooves. "
            "Massive sub-bass. "
            "The vibe is epic, dramatic, and powerful — Slavic soul meets African fire."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Russian aesthetic. "
            "Carved wood with Khokhloma golden/red floral patterns, matryoshka elements, "
            "onion dome silhouettes, Fabergé-inspired jewel details. "
            "Background: deep dark with rich red and gold imperial glow. "
            "GLOWING EYES (electric red or imperial gold). Russian folk + African tribal. "
            "Dramatic lighting, floating snowflakes and golden sparks. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Scottish",
        "secondary": "Scottish",
        "instruments": "bagpipes, fiddle (violin), clàrsach harp, snare drum, accordion",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Scottish instrumentation. "
            "122 BPM. Layer African percussion with bagpipe drones and melodies, fiddle reels, "
            "clàrsach harp, military snare drum rolls, and accordion. Highland energy over "
            "tribal grooves. Massive sub-bass. "
            "The vibe is epic, warrior-like, and majestic — Highland warrior meets African warrior."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Scottish Highland aesthetic. "
            "Carved wood with tartan plaid patterns, thistle motifs, "
            "Celtic knotwork, claymore sword silhouette. "
            "Background: deep dark misty highland with purple heather glow. "
            "GLOWING EYES (electric violet or steel blue). Tartan + African tribal patterns. "
            "Dramatic lighting, highland mist and floating embers. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Nordic/Viking",
        "secondary": "Nordic Viking",
        "instruments": "nyckelharpa, Hardanger fiddle, lur horn, tagelharpa, birch bark flute",
        "music_style": (
            "Create an EPIC fusion blending Afro House with Nordic/Viking instrumentation. "
            "122 BPM. Layer African percussion with nyckelharpa melodies, Hardanger fiddle, "
            "deep lur horn blasts, tagelharpa bowing, and birch bark flute. Viking war chants "
            "over tribal rhythms. Massive sub-bass. "
            "The vibe is dark, primal, and epic — Viking raids meet African ritual."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Viking aesthetic. "
            "Carved wood with Norse rune engravings, Viking knotwork, "
            "iron and silver accents, wolf/raven motifs. "
            "Background: deep dark aurora borealis glow (green/purple). "
            "GLOWING EYES (ice blue or fiery amber). Norse runes + African scarification. "
            "Dramatic lighting, northern lights, floating snow and embers. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Hungarian",
        "secondary": "Hungarian",
        "instruments": "cimbalom, tárogató, violin, hurdy-gurdy, zither",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Hungarian instrumentation. "
            "122 BPM. Layer African percussion with cimbalom cascades, tárogató melodies, "
            "passionate violin, hurdy-gurdy drones, and zither. Hungarian csárdás rhythms "
            "over tribal grooves. Massive sub-bass. "
            "The vibe is passionate, dark, and intoxicating — Magyar soul meets African spirit."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Hungarian folk aesthetic. "
            "Carved wood with Matyó embroidery floral patterns (red/blue/white), "
            "paprika-red accents, horseman motifs. "
            "Background: deep dark with warm paprika red and gold glow. "
            "GLOWING EYES (fiery red or electric blue). Hungarian floral + African tribal. "
            "Dramatic lighting, floating floral petals and sparks. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Italian",
        "secondary": "Italian",
        "instruments": "mandolin, accordion, violin, classical guitar, tarantella tambourine",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Italian instrumentation. "
            "122 BPM. Layer African percussion with mandolin tremolo, accordion, passionate violin, "
            "classical guitar, and tarantella tambourine. Mediterranean scales over tribal grooves. "
            "Massive sub-bass. "
            "The vibe is romantic, passionate, and cinematic — Napoli meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Italian Renaissance aesthetic. "
            "Carved wood with marble and gold leaf, Renaissance fresco patterns, "
            "Roman laurel wreath, Venetian mask elements. "
            "Background: deep dark with warm terracotta and gold glow. "
            "GLOWING EYES (warm gold or electric amber). Renaissance + African tribal. "
            "Dramatic lighting, floating golden particles and marble dust. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Portuguese Fado",
        "secondary": "Portuguese Fado",
        "instruments": "Portuguese guitar, classical guitar, violin, accordion, cavaquinho",
        "music_style": (
            "Create an EPIC fusion blending Afro House with Portuguese Fado instrumentation. "
            "122 BPM. Layer African percussion with Portuguese guitar (guitarra portuguesa), "
            "classical guitar, soulful violin, and melancholic fado vocals. "
            "Saudade-infused melodies over tribal grooves. Massive sub-bass. "
            "The vibe is melancholic, soulful, and deep — Lisbon meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Portuguese azulejo tile aesthetic. "
            "Carved wood with blue and white azulejo patterns, maritime motifs, "
            "golden Age of Discovery symbols. "
            "Background: deep dark Atlantic blue with golden lighthouse glow. "
            "GLOWING EYES (ocean blue or warm gold). Azulejo + African tribal patterns. "
            "Dramatic lighting, ocean mist and golden sparks. No text. 4K."
        ),
    },
    # ── AMERICAS ──
    {
        "name": "Afro House × Latin Folk",
        "secondary": "Latin Folk",
        "instruments": "charango, quena flute, cajón, maracas, pan flute, guitarrón",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Latin Folk instrumentation. "
            "122 BPM. Layer African percussion with Andean quena flute, charango strings, "
            "deep cajón rhythms, maracas, and pan flute melodies. Massive sub-bass. "
            "The vibe is fiery, cinematic, and passionate — Latin America meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Latin American folk art. "
            "Carved wood with Aztec/Mayan mosaic patterns, turquoise and jade inlays, "
            "feathered headdress elements (quetzal feathers), pre-Columbian gold ornaments. "
            "Background: deep dark with fiery orange/red/gold glow. "
            "GLOWING EYES (emerald green or fiery orange). Aztec + African tribal patterns. "
            "Dramatic lighting, floating embers and golden dust. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Brazilian",
        "secondary": "Brazilian",
        "instruments": "berimbau, cuíca, surdo drum, pandeiro, cavaquinho, atabaque",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Brazilian instrumentation. "
            "122 BPM. Layer African percussion with berimbau twang, cuíca friction drum, "
            "surdo bass drum, pandeiro tambourine, cavaquinho, and atabaque. "
            "Samba/capoeira rhythms fused with tribal grooves. Massive sub-bass. "
            "The vibe is carnival, euphoric, and electric — Brazil meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Brazilian carnival aesthetic. "
            "Carved wood with vibrant carnival feathers, sequins, golden Carnaval crown, "
            "tropical bird motifs, candomblé symbols. "
            "Background: deep dark with explosive neon carnival colors (green/yellow/blue). "
            "GLOWING EYES (electric green or neon yellow). Carnival + African tribal. "
            "Dramatic lighting, floating feathers and confetti sparks. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Native American",
        "secondary": "Native American",
        "instruments": "Native American flute, pow-wow drums, rattles, eagle bone whistle, water drum",
        "music_style": (
            "Create an EPIC fusion blending Afro House with Native American instrumentation. "
            "122 BPM. Layer African percussion with Native American cedar flute, "
            "pow-wow drum circles, rattles, and eagle bone whistle. "
            "Chant-based melodies over tribal grooves. Massive sub-bass. "
            "The vibe is spiritual, primal, and sacred — two ancient tribal cultures unite."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Native American aesthetic. "
            "Carved wood with eagle feather headdress, dreamcatcher elements, "
            "turquoise and silver jewelry, buffalo/eagle motifs. "
            "Background: deep dark prairie sunset with amber and turquoise glow. "
            "GLOWING EYES (turquoise or fiery amber). Native geometric + African tribal. "
            "Dramatic lighting, floating eagle feathers and spirit smoke. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Cuban",
        "secondary": "Cuban",
        "instruments": "tres guitar, bongos, timbales, güiro, trumpet, piano",
        "music_style": (
            "Create an EPIC fusion blending Afro House with Cuban Son/Salsa instrumentation. "
            "122 BPM. Layer African percussion with Cuban tres guitar, bongos, timbales, "
            "güiro scraper, salsa trumpet, and piano montunos. "
            "Son clave rhythms fused with tribal grooves. Massive sub-bass. "
            "The vibe is hot, infectious, and celebratory — Havana meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Cuban vintage aesthetic. "
            "Carved wood with vintage car chrome details, cigar-box patterns, "
            "tropical palm motifs, Havana architecture elements. "
            "Background: deep dark with warm sunset orange and turquoise glow. "
            "GLOWING EYES (electric turquoise or sunset orange). Cuban art + African tribal. "
            "Dramatic lighting, floating smoke and tropical sparks. No text. 4K."
        ),
    },
    # ── AFRICA (sub-genre fusions) ──
    {
        "name": "Afro House × Ethiopian Jazz",
        "secondary": "Ethiopian Jazz",
        "instruments": "krar (lyre), masenqo, washint flute, kebero drum, saxophone, piano",
        "music_style": (
            "Create an EPIC fusion blending Afro House with Ethiopian Jazz (Ethio-jazz). "
            "122 BPM. Layer African percussion with krar lyre, masenqo fiddle, washint flute, "
            "kebero drum, saxophone, and piano. Ethiopian pentatonic scales (tizita, bati modes) "
            "over tribal grooves. Massive sub-bass. "
            "The vibe is soulful, smoky, and spiritual — Addis Ababa meets Lagos."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask with Ethiopian motifs. "
            "Carved wood with Ethiopian cross patterns, Ge'ez script decorations, "
            "coffee plant motifs, golden Axumite obelisk silhouette. "
            "Background: deep dark with warm amber and coffee-brown glow. "
            "GLOWING EYES (golden amber or deep brown). Ethiopian + West African tribal. "
            "Dramatic lighting, floating coffee beans and incense smoke. No text. 4K."
        ),
    },
    {
        "name": "Afro House × North African Gnawa",
        "secondary": "North African Gnawa",
        "instruments": "guembri (sintir), qraqeb (metal castanets), tbel drum, ney flute, bendir",
        "music_style": (
            "Create an EPIC fusion blending Afro House with North African Gnawa music. "
            "122 BPM. Layer West African percussion with guembri bass lute, qraqeb metal castanets, "
            "tbel drum, ney flute, and bendir frame drum. Gnawa trance rhythms "
            "over house grooves. Massive sub-bass. "
            "The vibe is trance-like, spiritual, and ritualistic — Marrakech meets Lagos."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: two African masks — one Sub-Saharan, one North African Berber. "
            "Carved wood + silver Berber jewelry, Zellige tile patterns, "
            "Tuareg cross, henna designs, desert sand textures. "
            "Background: deep dark Saharan night with starlit golden glow. "
            "GLOWING EYES (desert gold or electric silver). Berber + Sub-Saharan patterns. "
            "Dramatic lighting, desert sand particles and starlight. No text. 4K."
        ),
    },
    # ── OCEANIA ──
    {
        "name": "Afro House × Aboriginal Australian",
        "secondary": "Aboriginal Australian",
        "instruments": "didgeridoo, clapsticks, bullroarer, gum leaf, bilma",
        "music_style": (
            "Create an EPIC fusion blending Afro House with Aboriginal Australian instrumentation. "
            "122 BPM. Layer African percussion with deep didgeridoo drones, clapstick rhythms, "
            "bullroarer effects, and circular breathing textures. "
            "Dreamtime atmospherics over tribal grooves. Massive sub-bass. "
            "The vibe is ancient, primal, and hypnotic — Dreamtime meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Aboriginal dot-painting aesthetic. "
            "Carved wood covered in intricate dot-painting patterns, ochre and white pigments, "
            "serpent/kangaroo dreamtime symbols, boomerang motifs. "
            "Background: deep dark Outback red earth with electric dot-art glow. "
            "GLOWING EYES (ochre orange or electric white). Dot-art + African tribal. "
            "Dramatic lighting, floating red sand and spirit particles. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Polynesian",
        "secondary": "Polynesian",
        "instruments": "pahu drum, ukulele, nose flute, toere slit drum, conch shell horn",
        "music_style": (
            "Create an EPIC fusion blending Afro House with Polynesian/Maori instrumentation. "
            "122 BPM. Layer African percussion with pahu drum, ukulele, nose flute, "
            "toere slit drum, and conch shell horn. Pacific Island chants "
            "over tribal grooves. Massive sub-bass. "
            "The vibe is oceanic, powerful, and ancestral — Pacific Islands meet Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Polynesian/Maori tiki aesthetic. "
            "Carved wood with Maori ta moko patterns, tiki god features, "
            "ocean wave motifs, tropical flower lei accents. "
            "Background: deep dark ocean blue with volcanic orange glow. "
            "GLOWING EYES (volcanic orange or ocean turquoise). Polynesian + African tribal. "
            "Dramatic lighting, ocean mist and volcanic embers. No text. 4K."
        ),
    },
    # ── CLASSICAL INSTRUMENT FUSIONS ──
    {
        "name": "Afro House × Violin",
        "secondary": "Classical Violin",
        "instruments": "solo violin, viola, cello, pizzicato strings, orchestral percussion",
        "music_style": (
            "Create an EPIC fusion blending Afro House with passionate solo violin and strings. "
            "122 BPM. Layer African percussion with a soaring solo violin melody, "
            "viola harmonies, deep cello bass lines, pizzicato accents, and orchestral percussion. "
            "Build dramatic crescendos over tribal grooves. Massive sub-bass. "
            "The vibe is cinematic, emotional, and powerful — orchestra meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING artwork: an African tribal mask with a VIOLIN integrated into the design. "
            "The mask's surface has violin f-holes carved in, strings running through it, "
            "bow-like details, musical staff patterns. "
            "Background: deep dark concert hall with dramatic golden spotlight. "
            "GLOWING EYES (electric gold or warm amber). Musical + African tribal. "
            "Dramatic lighting, floating musical notes and golden particles. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Piano",
        "secondary": "Piano",
        "instruments": "grand piano, electric piano (Rhodes), piano bass, celesta, harpsichord",
        "music_style": (
            "Create an EPIC fusion blending Afro House with grand piano and keyboard instruments. "
            "122 BPM. Layer African percussion with grand piano chords and runs, "
            "Rhodes electric piano warmth, deep piano bass, celesta sparkles, and harpsichord. "
            "Jazz-influenced piano over tribal grooves. Massive sub-bass. "
            "The vibe is sophisticated, deep, and soulful — concert hall meets African ritual."
        ),
        "thumbnail_style": (
            "A STUNNING artwork: an African tribal mask with PIANO KEYS integrated into the design. "
            "The mask has piano keys as teeth/jawline, grand piano curves merged with mask contours, "
            "golden music note ornaments. "
            "Background: deep dark with elegant ivory and ebony contrast, golden spotlight. "
            "GLOWING EYES (electric ivory white or deep golden). Piano + African tribal. "
            "Dramatic lighting, floating keys and golden dust. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Saxophone",
        "secondary": "Saxophone",
        "instruments": "alto saxophone, tenor saxophone, soprano sax, baritone sax, jazz organ",
        "music_style": (
            "Create an EPIC fusion blending Afro House with sultry saxophone solos. "
            "122 BPM. Layer African percussion with alto sax melodies, deep tenor sax, "
            "soprano sax riffs, baritone sax bass lines, and jazz organ pads. "
            "Smooth jazz runs over tribal grooves. Massive sub-bass. "
            "The vibe is sexy, smoky, and midnight — jazz club meets African festival."
        ),
        "thumbnail_style": (
            "A STUNNING artwork: an African tribal mask with a SAXOPHONE merged into the design. "
            "The mask has golden saxophone curves as horns, brass reflections, "
            "jazz-era art deco patterns, smoke wisps. "
            "Background: deep dark smoky jazz club with warm golden sax glow. "
            "GLOWING EYES (warm gold or neon blue). Art Deco + African tribal. "
            "Dramatic lighting, floating smoke and golden brass sparks. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Guitar",
        "secondary": "Guitar",
        "instruments": "acoustic guitar, electric guitar, bass guitar, 12-string guitar, slide guitar",
        "music_style": (
            "Create an EPIC fusion blending Afro House with guitar-driven energy. "
            "122 BPM. Layer African percussion with acoustic guitar fingerpicking, "
            "electric guitar riffs and solos, deep bass guitar grooves, "
            "12-string shimmer, and slide guitar. Rock/blues energy over tribal grooves. "
            "Massive sub-bass. "
            "The vibe is raw, electric, and powerful — rock arena meets African village."
        ),
        "thumbnail_style": (
            "A STUNNING artwork: an African tribal mask with ELECTRIC GUITAR elements. "
            "The mask has guitar pickups as eyes, fretboard patterns, "
            "lightning bolt accents, amplifier grill texture. "
            "Background: deep dark with electric neon purple and orange stage lighting. "
            "GLOWING EYES (electric purple or neon orange). Rock + African tribal. "
            "Dramatic lighting, electric sparks and stage smoke. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Cello",
        "secondary": "Cello",
        "instruments": "solo cello, double bass, cello ensemble, pizzicato cello, arco strings",
        "music_style": (
            "Create an EPIC fusion blending Afro House with deep, emotional cello. "
            "122 BPM. Layer African percussion with solo cello melody, double bass depth, "
            "cello ensemble harmonies, pizzicato rhythms, and arco string swells. "
            "Dark, dramatic classical passages over tribal grooves. Massive sub-bass. "
            "The vibe is dark, cinematic, and profoundly emotional — symphony meets ritual."
        ),
        "thumbnail_style": (
            "A STUNNING artwork: an African tribal mask with CELLO integrated into the design. "
            "The mask has cello scroll as crown, f-holes carved in cheeks, "
            "bow-hair texture as decoration, deep wood grain patterns. "
            "Background: deep dark with warm amber and deep burgundy glow. "
            "GLOWING EYES (warm amber or deep burgundy). Classical + African tribal. "
            "Dramatic lighting, floating string vibrations and ember particles. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Trumpet & Brass",
        "secondary": "Trumpet & Brass",
        "instruments": "trumpet, trombone, French horn, flugelhorn, tuba, brass ensemble",
        "music_style": (
            "Create an EPIC fusion blending Afro House with powerful brass section. "
            "122 BPM. Layer African percussion with trumpet fanfares, trombone slides, "
            "French horn swells, flugelhorn warmth, and full brass ensemble blasts. "
            "Brass stabs and jazzy runs over tribal grooves. Massive sub-bass. "
            "The vibe is triumphant, massive, and victorious — brass band meets African warriors."
        ),
        "thumbnail_style": (
            "A STUNNING artwork: an African tribal mask with BRASS INSTRUMENTS merged in. "
            "The mask has trumpet bell as mouth, brass tubing as decoration, "
            "golden valves as ornaments, polished brass reflections. "
            "Background: deep dark with blazing golden brass spotlight. "
            "GLOWING EYES (blazing gold or electric copper). Brass + African tribal. "
            "Dramatic lighting, golden light rays and metallic sparks. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Harp",
        "secondary": "Harp",
        "instruments": "concert harp, Celtic harp, electric harp, lyre, zither",
        "music_style": (
            "Create an EPIC fusion blending Afro House with ethereal harp instrumentation. "
            "122 BPM. Layer African percussion with concert harp glissandos and arpeggios, "
            "Celtic harp melodies, electric harp effects, lyre plucks, and zither. "
            "Heavenly cascading notes over tribal grooves. Massive sub-bass. "
            "The vibe is ethereal, angelic, and transcendent — heaven meets earth."
        ),
        "thumbnail_style": (
            "A STUNNING artwork: an African tribal mask with HARP strings running through it. "
            "The mask has golden harp frame as crown, strings as tears/decoration, "
            "angelic wing motifs, crystalline details. "
            "Background: deep dark with ethereal white and gold divine light. "
            "GLOWING EYES (pure white or celestial gold). Angelic + African tribal. "
            "Dramatic lighting, floating golden particles and light rays. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Organ & Church",
        "secondary": "Church Organ",
        "instruments": "pipe organ, Hammond organ, church bells, choir vocals, gospel piano",
        "music_style": (
            "Create an EPIC fusion blending Afro House with massive church organ and gospel. "
            "122 BPM. Layer African percussion with pipe organ power chords, "
            "Hammond organ grooves, church bells, choir vocal layers, and gospel piano. "
            "Sacred hymn progressions over tribal grooves. Massive sub-bass. "
            "The vibe is sacred, massive, and transcendent — cathedral meets African temple."
        ),
        "thumbnail_style": (
            "A STUNNING artwork: an African tribal mask inside a GOTHIC CATHEDRAL setting. "
            "The mask has stained glass patterns, pipe organ pipes as crown/horns, "
            "golden cross motifs, cathedral arch frame. "
            "Background: deep dark cathedral interior with divine light beams. "
            "GLOWING EYES (stained glass multicolor or divine gold). Gothic + African tribal. "
            "Dramatic lighting, dust motes in light beams, floating incense. No text. 4K."
        ),
    },
    # ── MORE WORLD GENRES ──
    {
        "name": "Afro House × Jamaican Reggae/Dub",
        "secondary": "Jamaican Reggae",
        "instruments": "melodica, steel drums, reggae guitar, dub bass, nyabinghi drums",
        "music_style": (
            "Create an EPIC fusion blending Afro House with Jamaican Reggae/Dub instrumentation. "
            "122 BPM. Layer African percussion with melodica, steel drums, offbeat reggae guitar, "
            "deep dub bass lines with heavy reverb, and nyabinghi drums. "
            "Dub echo effects over tribal grooves. Massive sub-bass. "
            "The vibe is chill, deep, and spiritual — Kingston meets Lagos."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Jamaican Rastafari aesthetic. "
            "Carved wood with red/gold/green color scheme, lion of Judah motifs, "
            "dreadlock-like raffia, palm leaf patterns. "
            "Background: deep dark with rasta red/gold/green gradient glow. "
            "GLOWING EYES (electric green or golden). Jamaican + African tribal. "
            "Dramatic lighting, floating smoke and tropical sparks. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Hawaiian",
        "secondary": "Hawaiian",
        "instruments": "steel guitar, ukulele, slack-key guitar, ipu gourd drum, pahu drum",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Hawaiian instrumentation. "
            "122 BPM. Layer African percussion with Hawaiian steel guitar slides, "
            "ukulele strumming, slack-key guitar, ipu gourd drum, and pahu drum. "
            "Island melodies over tribal grooves. Massive sub-bass. "
            "The vibe is tropical, dreamy, and warm — Hawaiian paradise meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Hawaiian tiki aesthetic. "
            "Carved wood with hibiscus flowers, volcanic rock texture, "
            "tiki god elements, ocean wave motifs, plumeria lei. "
            "Background: deep dark tropical sunset with orange/purple volcanic glow. "
            "GLOWING EYES (volcanic orange or ocean blue). Tiki + African tribal. "
            "Dramatic lighting, floating plumeria petals and volcanic embers. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Mongolian",
        "secondary": "Mongolian",
        "instruments": "morin khuur (horsehead fiddle), throat singing, yatga, tovshuur, limbe flute",
        "music_style": (
            "Create an EPIC fusion blending Afro House with Mongolian throat singing and instruments. "
            "122 BPM. Layer African percussion with morin khuur fiddle, deep throat singing "
            "(khoomei/sygyt overtone), yatga zither, tovshuur lute, and limbe flute. "
            "Vast steppe atmospherics over tribal grooves. Massive sub-bass. "
            "The vibe is vast, primal, and otherworldly — Mongolian steppe meets African savanna."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Mongolian warrior aesthetic. "
            "Carved wood with Mongolian armor details, horsehair decoration, "
            "eagle motifs, ger (yurt) geometric patterns, sky-blue silk. "
            "Background: deep dark endless steppe with dramatic sky-blue and gold glow. "
            "GLOWING EYES (sky blue or fierce gold). Mongolian + African tribal. "
            "Dramatic lighting, floating horsehair and steppe dust. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Thai",
        "secondary": "Thai",
        "instruments": "ranat ek (xylophone), khim, pi (oboe), saw duang fiddle, klong drum",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Thai instrumentation. "
            "122 BPM. Layer African percussion with ranat ek xylophone cascades, "
            "khim hammered dulcimer, pi oboe, saw duang fiddle, and klong drum. "
            "Thai pentatonic scales over tribal grooves. Massive sub-bass. "
            "The vibe is ornate, mystical, and regal — Thai temple meets African ritual."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Thai royal aesthetic. "
            "Carved wood with golden Thai temple patterns, Naga serpent details, "
            "lotus motifs, jeweled crown (chada), emerald accents. "
            "Background: deep dark with golden temple glow and emerald light. "
            "GLOWING EYES (emerald green or royal gold). Thai + African tribal. "
            "Dramatic lighting, floating lotus petals and golden sparks. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Indonesian Gamelan",
        "secondary": "Indonesian Gamelan",
        "instruments": "gamelan gongs, metallophones, kendang drum, suling flute, rebab",
        "music_style": (
            "Create an EPIC fusion blending Afro House with Indonesian Gamelan orchestration. "
            "122 BPM. Layer African percussion with gamelan gong cascades, metallophone melodies, "
            "kendang drum patterns, suling bamboo flute, and rebab bowing. "
            "Interlocking gamelan patterns over tribal grooves. Massive sub-bass. "
            "The vibe is hypnotic, shimmering, and trance-like — Bali meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Balinese Barong mask aesthetic. "
            "Carved wood combining African and Balinese demon-mask styles, "
            "golden filigree, batik patterns, temple guardian details. "
            "Background: deep dark with shimmering bronze/gold gamelan glow. "
            "GLOWING EYES (electric bronze or fiery red). Balinese + African tribal. "
            "Dramatic lighting, floating incense smoke and metallic sparks. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Filipino",
        "secondary": "Filipino",
        "instruments": "kulintang gongs, kudyapi lute, tongali flute, dabakan drum, gangsa",
        "music_style": (
            "Create an EPIC fusion blending Afro House with traditional Filipino instrumentation. "
            "122 BPM. Layer African percussion with kulintang gong melodies, kudyapi lute, "
            "tongali nose flute, dabakan drum, and gangsa flat gongs. "
            "Island rhythms over tribal grooves. Massive sub-bass. "
            "The vibe is vibrant, island-spirit, and powerful — Philippines meets Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Filipino tribal aesthetic. "
            "Carved wood with T'boli/Ifugao tribal patterns, brass gong textures, "
            "rice terrace motifs, tattoo-inspired designs (batok). "
            "Background: deep dark with warm bronze and tropical green glow. "
            "GLOWING EYES (bronze or electric teal). Filipino tribal + African tribal. "
            "Dramatic lighting, floating tropical leaves and bronze sparks. No text. 4K."
        ),
    },
    {
        "name": "Afro House × Tibetan",
        "secondary": "Tibetan",
        "instruments": "singing bowls, dungchen (long horn), dramyin, gyaling oboe, nga drum",
        "music_style": (
            "Create an EPIC fusion blending Afro House with Tibetan Buddhist instrumentation. "
            "122 BPM. Layer African percussion with singing bowl overtones, "
            "deep dungchen long horn blasts, dramyin lute, gyaling oboe, and nga drum. "
            "Monk chant textures over tribal grooves. Massive sub-bass. "
            "The vibe is meditative, vast, and transcendent — Himalayas meet Africa."
        ),
        "thumbnail_style": (
            "A STUNNING fusion: African tribal mask MERGED with Tibetan Buddhist aesthetic. "
            "Carved wood with mandala patterns, prayer wheel motifs, "
            "dharma wheel symbols, turquoise and coral inlays, golden Buddha details. "
            "Background: deep dark mountain night with peaceful golden/turquoise glow. "
            "GLOWING EYES (turquoise or warm gold). Tibetan + African tribal. "
            "Dramatic lighting, floating prayer flags and incense smoke. No text. 4K."
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
