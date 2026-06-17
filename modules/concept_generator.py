import json
import re
import time
from dataclasses import dataclass
from openai import OpenAI
from config import OPENAI_API_KEY, MUSIC_GENRE, MUSIC_STYLE_PROMPT, THUMBNAIL_STYLE_PROMPT, WORLD_CUP_THEME
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
    # Optional generated lyrics — used by platforms that accept a lyrics field
    # (e.g. Suno Advanced mode). Empty means instrumental.
    lyrics: str = ""


# Default style prompts per genre (used when no custom prompt is set)
DEFAULT_AFRO_HOUSE_STYLE = (
    "Create a progressive Afro House × Deep Bass House remix-style track infused "
    "with massive car bass and deep, psychedelic tribal energy. Tempo 122 BPM. "
    "Blend organic percussion (congas, shakers, djembe, bongos, log drums) with "
    "modern deep house production: rolling 4-on-the-floor kick, plucked deep "
    "house bassline that hits in the chest, side-chained sub-bass, and warm "
    "analog low-end. Layer psychedelic textures, evolving atmospheric pads, "
    "filter sweeps, and subtle vocal tribal chants that echo through wide "
    "stereo space. Introduce dark, evolving synth arps, tape-style risers, and "
    "remix-style breakdowns/build-ups that drop into a cinematic festival-style "
    "groove. The vibe should feel like a deep house remix of a sacred Afro "
    "anthem — spiritual yet club-ready, balancing Afro rhythms with deep bass "
    "house resonance, perfect for big sound systems, car audio, and open-air "
    "sets. Mastered loud and warm with serious sub-bass impact."
)

DEFAULT_THUMBNAIL_PROMPT = (
    "A dramatic, hyper-detailed AUTHENTIC African tribal mask centered on a deep dark background, "
    "designed as a SCROLL-STOPPING YouTube thumbnail for an Afro House × Deep Bass House remix. "
    "Each mask must be COMPLETELY UNIQUE — vary the tribe/region inspiration: "
    "Yoruba, Dogon, Fang, Punu, Dan, Kuba, Chokwe, Makonde, Baule, Songye, Luba, Bamana. "
    "Authentic patterns, materials and colors from real African art traditions: carved wood "
    "with rich patina, cowrie shells, raffia, brass ornaments, scarification marks, geometric "
    "tribal patterns, ritual paint in ochre/indigo/kaolin white. "
    "CRITICAL CTR DETAILS: The mask MUST have EXTREMELY INTENSE GLOWING EYES with supernatural "
    "energy (neon gold, electric blue, fiery orange, or molten lava red — choose ONE per image, "
    "make it look ALIVE and otherworldly). EXTREME HIGH CONTRAST — pitch-dark background with "
    "explosive bursts of saturated color (magenta, electric blue, glowing amber). Dramatic rim "
    "lighting from one side, volumetric smoke, floating embers, mystical particles, festival "
    "laser beams cutting through haze, sub-bass shockwave ripples in the air. The mask takes up "
    "60-70% of the frame, perfectly CENTERED, hyper-sharp focus on the face. "
    "No text or letters on the image. "
    "Cinematic 8K poster quality — sacred artifact meets deep bass house album cover. The image "
    "must POP at small sizes (mobile YouTube feed) and feel both ancient/spiritual and club-ready."
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


# ── Per-genre creative profiles ──
# Each profile tailors the AI prompt so track names, titles, thumbnails, and
# social copy fit the ACTUAL genre instead of defaulting to Afro/tribal vibes.
GENRE_PROFILES: dict[str, dict] = {
    "afro house": {
        "name_vibe": (
            "exotic African-inspired invented words that sound like names of tribes, "
            "rivers, spirits, or ancestral places — rhythmic, two syllables preferred"
        ),
        "name_examples": "Bakari, Djenné, Kisumu, Makossa, Ngoma, Safiri, Tabora, Owari, Gajani, Lumba, Echoro, Haruna, Fikiri, Zaharu",
        "power_words": "ADDICTIVE, LEGENDARY, FORBIDDEN, GODLY, SACRED, PRIMAL, EPIC, INSANE, MASSIVE, UNREAL, TRIBAL, ANCESTRAL, SPIRITUAL, HYPNOTIC, DEEP, REMIX",
        # Compilation-mix titles in the same style as the Dark House channel,
        # tuned for an Afro House × Deep Bass House Remix vibe. {mix_number}
        # is auto-incremented per run via _next_mix_number(genre).
        "title_formulas": (
            "- TRACKNAME 🔥 This Afro House Beat Will Give You CHILLS #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 You Won't Believe This Drop • Afro House Mix #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 The ONLY Afro House Mix You Need Right Now #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 WARNING: This Beat Is DANGEROUSLY Addictive #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 I Can't Stop Listening To This Afro House Mix #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 This Is What PEAK Afro House Sounds Like #{mix_number} 2026 | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Play This At MAX VOLUME • Afro House #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 The Beat That Broke The Internet #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 INSANE Tribal Drums × Deep Bass #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Once You Hear This, You Can't Unhear It #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Afro House Mix • Deep Bass / Tribal Energy #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 The Most ADDICTIVE Afro House Remix of 2026 #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Best Afro House Mix For Long Drives & Gym #{mix_number} 2026 | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Hidden Gem Afro House Track Nobody Talks About #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Real Afro House Lovers ONLY • Mix #{mix_number} 2026 | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Africa's Best Kept Secret • Afro House Mix #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 From The Heart Of Africa • Afro House Mix #{mix_number} 2026 | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Premium Afro House Selection • Mix #{mix_number} 2026 | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Soulful Afro House Vibes For Late Nights #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Smooth Afro House For Sunset Sessions #{mix_number} 2026 | {genre_hashtag}\n"
            "- TRACKNAME 🔥 This Track Made Me Fall In Love With Afro House #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Pure Tribal Energy • Afro House Mix #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Afro House Mix For Workouts & Festival Vibes #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 The Mix That Changed My Playlist Forever #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Sunrise Drive • Afro House Mix #{mix_number} 2026 | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Spiritual Afro House Journey • Mix #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Afro House That Hits DIFFERENT • Mix #{mix_number} 2026 | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Drop The Bass • Tribal Afro House Mix #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 If You Love Afro House, You NEED This #{mix_number} 2026 | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Late Night Tribal Drive • Afro House Mix #{mix_number} | {genre_hashtag}"
        ),
        "thumbnail_core": (
            "A BOLD minimalist YouTube thumbnail: ONE striking close-up subject — either a "
            "carved ceremonial African mask (Yoruba, Dogon, Fang, Punu, Dan, Kuba, Chokwe, "
            "Makonde, Baule, Songye, Luba, Bamana style) OR a powerful young African warrior / "
            "queen / shaman portrait with intense piercing eyes. STYLE: ultra-realistic, "
            "cinematic, painted-poster look (NOT photography, NOT 3D render). "
            "Subject fills 70-80% of the frame, slightly off-center, looking forward. "
            "PALETTE: limited to 3 colors max — deep gold or molten copper as accent, "
            "rich dark brown / black background, optional ember-orange highlight. "
            "STRONG rim light on one side of the face creates EXTREME contrast — face "
            "POPS off the dark background. NO smoke, NO sparks, NO dust, NO clutter, "
            "NO sci-fi, NO modern elements, NO neon, NO text. Just one powerful subject + "
            "dramatic light + dark background. Think Drake/Beyoncé album cover meets "
            "African heritage. Mood: powerful, magnetic, hypnotic. 4K, ultra sharp focus."
        ),
        "related_genres": "deep house, tribal house, organic house, melodic house, african house music, afro tribal, ethnic house, progressive house",
        "use_cases": "gym workout music, driving music, DJ sets, festival music, meditation, car bass music, late night vibes, sunset sessions",
        "tiktok_hooks": (
            "'This beat hits different 🔥', 'Name a better {genre} track, I'll wait 🎧', "
            "'POV: you found the perfect {genre} gem 💎', 'When the tribal drums kick in 🥁🔥', "
            "'Put this on repeat 🔁🔥'"
        ),
    },
    "dark house": {
        "name_vibe": (
            "short, cinematic, nocturnal invented words that evoke neon-lit rain, obsession, "
            "smoke, velvet shadows and late-night cityscapes — sultry, mysterious, single word preferred"
        ),
        "name_examples": "Noctis, Obskura, Vertigo, Kinesis, Sable, Velora, Halcyon, Mirage, Crimson, Ember, Zephira, Phantasm, Violette, Lumen, Nyxara",
        "power_words": "HAUNTING, SEDUCTIVE, HYPNOTIC, NEON, ADDICTIVE, FORBIDDEN, CINEMATIC, OBSESSIVE, MIDNIGHT, MELANCHOLIC, SULTRY, INSANE, VELVET, AFTER-DARK",
        # Dark House uses compilation-style titles like:
        #   "Deep House Mix • Chill / Night Vibes / Stress Relief #8 dark"
        # {mix_number} is auto-incremented per run via _next_mix_number(genre).
        "title_formulas": (
            "- TRACKNAME 🔥 Deep House Mix • Chill / Night Vibes / Stress Relief #{mix_number} Dark | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Dark Deep House Mix • Late Night Drive / Neon Rain #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Deep House Mix • Midnight Mood / Chill Lounge #{mix_number} Dark | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Dark House Mix • Night Drive / Stress Relief #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Deep House Mix • After Dark / Sultry Vibes #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Dark Deep House Mix • Insomnia / Cinematic Night #{mix_number} | {genre_hashtag}\n"
            "- TRACKNAME 🔥 Deep House Mix • Velvet Midnight / Study Focus #{mix_number} Dark | {genre_hashtag}"
        ),
        "thumbnail_core": (
            "A cinematic noir scene: rain-slick neon-lit city street at night, wet asphalt reflecting "
            "purple and electric blue lights, soft female silhouette in the distance, film grain, "
            "volumetric fog, dreamy blurred bokeh. Dark moody palette (deep purple, midnight blue, "
            "magenta accents). Cinematic wide shot aesthetic. Evokes obsession, desire, late-night "
            "loneliness. 60-70% frame composition, HIGH CONTRAST so it pops as a YouTube thumbnail."
        ),
        "related_genres": "melodic techno, progressive house, deep house, organic house, melodic house, chillwave, synthwave, dark progressive",
        "use_cases": "late night drive, rainy night vibes, study focus music, insomnia, cinematic moments, rooftop lounges, chill club sets, after-dark playlists",
        "tiktok_hooks": (
            "'POV: 3am, neon lights, this track 🌧️', 'This hits when the rain starts 🌧️🔥', "
            "'Night drive energy is UNREAL 🚗✨', 'Put this on and lose yourself 🌌', "
            "'Midnight mood activated 🌃'"
        ),
    },
    "phonk": {
        "name_vibe": (
            "aggressive, drift-racer, Memphis-flavored invented words — short, hard, cyrillic-leaning, "
            "evoking skulls, smoke, demons, night streets"
        ),
        "name_examples": "Krovavy, Molot, Vostok, Drift, Sable, Raptor, Venom, Obsidian, Saber, Demon, Mayhem, Stalker, Zverь, Nyktos",
        "power_words": "HARD, AGGRESSIVE, DEMONIC, BRUTAL, UNDERGROUND, SLAY, DRIFT, MEMPHIS, INSANE, VIOLENT, RAW, DARK",
        "title_formulas": (
            "- TRACKNAME 🔥 HARD {genre} | Drift Phonk 2026 | {genre_hashtag}\n"
            "- TRACKNAME 🔥 AGGRESSIVE {genre} Mix | Brazilian Drift Vibes | {genre_hashtag}\n"
            "- TRACKNAME 🔥 DEMONIC {genre} Drop | Tire Smoke Energy | {genre_hashtag}\n"
            "- TRACKNAME 🔥 UNDERGROUND {genre} | Memphis Cowbell Mayhem | {genre_hashtag}\n"
            "- TRACKNAME 🔥 BRUTAL {genre} Track That Hits DIFFERENT | {genre_hashtag}\n"
            "- TRACKNAME 🔥 The {genre} Track Every Drift Edit NEEDS | {genre_hashtag}"
        ),
        "thumbnail_core": (
            "A drifting sports car at night wreathed in thick tire smoke, glowing red brake lights, "
            "neon signs and grimy urban backdrop. Optional demonic skull or grim reaper silhouette "
            "with glowing red eyes. Color palette: deep black, blood red, amber, electric white. "
            "Gritty grainy texture, motion blur, dramatic low-angle composition, HIGH CONTRAST."
        ),
        "related_genres": "drift phonk, brazilian phonk, memphis phonk, house phonk, aggressive phonk, trap, hard bass",
        "use_cases": "drift edits, gym music, car bass, workout motivation, gaming, street racing videos, sigma edits",
        "tiktok_hooks": (
            "'This phonk is UNREAL 🔥🚗', 'Drift edit material 💨', 'POV: the villain arc starts 😈', "
            "'Gym went different with this on 💪🔥', 'Sigma activated 🗿'"
        ),
    },
    "techno": {
        "name_vibe": (
            "futurist / industrial invented words — short, metallic, cryptic, evoking circuitry, "
            "warehouses, machines, synthetic futures"
        ),
        "name_examples": "Axon, Vector, Nyx, Ion, Cipher, Apex, Quanta, Helios, Aurex, Kryon, Volt, Mira, Pyx, Zenos",
        "power_words": "RELENTLESS, POUNDING, WAREHOUSE, INDUSTRIAL, HYPNOTIC, PEAK-TIME, UNDERGROUND, BERLIN, DRIVING, RAW, MASSIVE",
        "title_formulas": (
            "- TRACKNAME 🔥 RELENTLESS {genre} | Peak-Time Warehouse Mix | {genre_hashtag}\n"
            "- TRACKNAME 🔥 HYPNOTIC {genre} Drop | Berlin Underground 2026 | {genre_hashtag}\n"
            "- TRACKNAME 🔥 POUNDING {genre} Track | Industrial Energy | {genre_hashtag}\n"
            "- TRACKNAME 🔥 The {genre} Banger That SHOOK The Dancefloor | {genre_hashtag}\n"
            "- TRACKNAME 🔥 RAW {genre} | Driving 4x4 Kick, Acid Stabs | {genre_hashtag}"
        ),
        "thumbnail_core": (
            "A brutalist concrete warehouse interior lit by intense strobe lights, silhouetted crowd, "
            "laser beams cutting through fog, industrial pipes and machinery. Color palette: stark "
            "black and white with one vivid accent (acid green, hot pink, or ice blue). Harsh "
            "high-contrast lighting, minimalist geometric composition. No text."
        ),
        "related_genres": "melodic techno, peak time techno, hard techno, industrial techno, progressive house, minimal techno",
        "use_cases": "warehouse raves, gym workouts, focus coding music, festival main stage, late night driving, rave playlists",
        "tiktok_hooks": (
            "'When the kick drops 🥁⚡', 'Berlin warehouse energy 🖤', 'This techno is UNREAL 🔥', "
            "'Peak time vibes 🌌', 'Gym PR unlocked 💪'"
        ),
    },
    "melodic techno": {
        "name_vibe": "ethereal, celestial, melancholic invented words — evoking cosmos, glaciers, auroras",
        "name_examples": "Aurora, Celeste, Nivara, Solaria, Etheros, Lumina, Nebula, Arkana, Solstice, Elysia, Kyros",
        "power_words": "EMOTIONAL, CINEMATIC, CELESTIAL, HYPNOTIC, ETHEREAL, MASSIVE, INSANE, UNREAL, TRANSCENDENT, SOULFUL",
        "title_formulas": (
            "- TRACKNAME 🔥 EMOTIONAL {genre} | Afterlife-Style Extended Mix | {genre_hashtag}\n"
            "- TRACKNAME 🔥 CINEMATIC {genre} Drop | Melodic Journey 2026 | {genre_hashtag}\n"
            "- TRACKNAME 🔥 CELESTIAL {genre} | Tale of Us Vibes | {genre_hashtag}\n"
            "- TRACKNAME 🔥 The {genre} Track That Made Everyone Cry On The Dancefloor | {genre_hashtag}\n"
            "- TRACKNAME 🔥 HYPNOTIC {genre} Journey | Sunset Set Gem | {genre_hashtag}"
        ),
        "thumbnail_core": (
            "A vast cinematic landscape at twilight: endless desert, glacier, or cosmic nebula. "
            "A lone silhouetted figure facing the horizon. Aurora lights or celestial glow. "
            "Palette: deep indigo, violet, rose gold, soft amber. Dreamy, ethereal, emotional. "
            "Wide cinematic composition, soft film grain, HIGH CONTRAST."
        ),
        "related_genres": "melodic house, progressive house, organic house, deep house, afterlife style, tale of us style, anjunadeep",
        "use_cases": "sunset sessions, desert raves, emotional driving, meditation, festival main stage, cinematic playlists",
        "tiktok_hooks": (
            "'Goosebumps from this drop 🌌', 'When the melody hits 😭🔥', 'Afterlife energy 🌅', "
            "'This melodic techno is UNREAL ✨'"
        ),
    },
    "deep house": {
        "name_vibe": "smooth, soulful, sun-soaked invented words — evoking beaches, ibiza sunsets, cocktails",
        "name_examples": "Solara, Marea, Sienna, Cala, Azura, Lumbra, Ondara, Velvana, Iberia, Estio, Noira",
        "power_words": "SMOOTH, SOULFUL, IBIZA, SUNSET, GROOVY, ADDICTIVE, HYPNOTIC, EMOTIONAL, DEEP, CLASSIC",
        "title_formulas": (
            "- TRACKNAME 🔥 SMOOTH {genre} | Ibiza Sunset Mix 2026 | {genre_hashtag}\n"
            "- TRACKNAME 🔥 SOULFUL {genre} Groove | Balearic Vibes | {genre_hashtag}\n"
            "- TRACKNAME 🔥 ADDICTIVE {genre} Track | Poolside Extended Mix | {genre_hashtag}\n"
            "- TRACKNAME 🔥 The {genre} Gem Every DJ Is Playing | {genre_hashtag}"
        ),
        "thumbnail_core": (
            "An Ibiza-style sunset scene: infinity pool, white architecture, palm silhouettes, "
            "warm amber and magenta sky. Optional female silhouette with cocktail. "
            "Palette: golden hour amber, rose pink, deep turquoise. Dreamy, aspirational, luxurious. "
            "HIGH CONTRAST cinematic composition."
        ),
        "related_genres": "soulful house, tech house, organic house, melodic house, balearic, jackin house, afro house",
        "use_cases": "poolside sessions, beach clubs, sunset driving, cocktail hours, summer workouts, chill DJ sets",
        "tiktok_hooks": (
            "'Ibiza sunset vibes 🌅', 'Poolside energy unlocked 🍹', 'This groove is addictive 🕺', "
            "'When the bassline hits 🎧🔥'"
        ),
    },
    "lo-fi": {
        "name_vibe": "calm, poetic, urban-nostalgic invented words — evoking rain, tea, paper, quiet rooms",
        "name_examples": "Paperline, Velour, Koi, Tatami, Moth, Linen, Rainfall, Yugen, Kinoko, Amari, Yori",
        "power_words": "COZY, DREAMY, NOSTALGIC, CALM, RAINY, STUDY, FOCUSED, MELLOW, CHILL, SOOTHING",
        "title_formulas": (
            "- TRACKNAME 🌧️ COZY Lo-Fi Beat | Study & Chill Mix | {genre_hashtag}\n"
            "- TRACKNAME 🌧️ DREAMY {genre} | Rainy Afternoon Vibes | {genre_hashtag}\n"
            "- TRACKNAME 🌧️ NOSTALGIC {genre} Beat to Relax To | {genre_hashtag}\n"
            "- TRACKNAME 🌧️ The {genre} Track That Feels Like a Warm Hug | {genre_hashtag}"
        ),
        "thumbnail_core": (
            "A cozy bedroom or café scene at dusk, rain on the window, warm lamp light, steaming cup of tea, "
            "an anime-style character reading or gazing out. Palette: warm amber, soft pink, muted teal. "
            "Soft grainy illustration style (Studio Ghibli / lo-fi girl aesthetic). Calm, nostalgic, dreamy."
        ),
        "related_genres": "chillhop, jazzhop, lofi hip hop, bedroom beats, study beats, ambient, chillwave",
        "use_cases": "studying, reading, coding, sleeping, rainy day vibes, yoga, morning routines",
        "tiktok_hooks": (
            "'Study session unlocked 📚🌧️', 'Rainy afternoon mood ☕', 'Cozy vibes only 🫖', "
            "'This beat is a warm hug 🧡'"
        ),
    },
    "trap": {
        "name_vibe": "gritty, street, short hard invented words with edge — evoke money, night, hustle",
        "name_examples": "Onyx, Krypto, Zaga, Vexx, Rico, Sable, Vantta, Kobra, Drayko, Styx",
        "power_words": "HARD, HEAVY, DIRTY, INSANE, UNDERGROUND, STREET, VIRAL, BANGER, SAVAGE, RAW",
        "title_formulas": (
            "- TRACKNAME 🔥 HARD {genre} Beat 2026 | Street Banger | {genre_hashtag}\n"
            "- TRACKNAME 🔥 HEAVY {genre} | 808 Mayhem | {genre_hashtag}\n"
            "- TRACKNAME 🔥 INSANE {genre} Drop | Underground Fire | {genre_hashtag}\n"
            "- TRACKNAME 🔥 The {genre} Beat Every Rapper Needs | {genre_hashtag}"
        ),
        "thumbnail_core": (
            "A gritty urban night scene: neon-lit alley, chain-link fence, skyline silhouette. "
            "Gold chains, diamond glint, smoke. Palette: deep black, gold, blood red, neon purple. "
            "High-contrast street photography aesthetic with grainy film texture."
        ),
        "related_genres": "drill, hip hop, rap, trap beats, hard trap, dark trap, type beat",
        "use_cases": "gym workouts, driving, gaming, hype moments, freestyle, rap beats",
        "tiktok_hooks": (
            "'This beat is HARD 🔥', 'Type beat energy 💯', 'Gym mode activated 💪', "
            "'When the 808 hits 🔊'"
        ),
    },
    "drum and bass": {
        "name_vibe": "fast, kinetic, futuristic invented words — evoking speed, circuits, neon",
        "name_examples": "Voltara, Kinetix, Pulsar, Axiom, Neuros, Cyphera, Jungla, Volt, Nexis, Syra",
        "power_words": "FAST, RELENTLESS, LIQUID, NEUROFUNK, JUNGLE, HEAVY, MASSIVE, INSANE, EXPLOSIVE",
        "title_formulas": (
            "- TRACKNAME 🔥 RELENTLESS {genre} | Neurofunk Banger 2026 | {genre_hashtag}\n"
            "- TRACKNAME 🔥 HEAVY {genre} Drop | Liquid Vibes | {genre_hashtag}\n"
            "- TRACKNAME 🔥 EXPLOSIVE {genre} Mix | 174 BPM Fire | {genre_hashtag}\n"
            "- TRACKNAME 🔥 The {genre} Track That Destroyed The Club | {genre_hashtag}"
        ),
        "thumbnail_core": (
            "Futuristic cyberpunk scene: neon-drenched city, speeding light trails, cybernetic figure. "
            "Palette: electric cyan, magenta, deep black. Motion blur, glitch effects, "
            "high-energy composition. HIGH CONTRAST."
        ),
        "related_genres": "dnb, jungle, neurofunk, liquid dnb, drum n bass, breakbeat",
        "use_cases": "gym workouts, running, gaming, driving, festival sets, adrenaline playlists",
        "tiktok_hooks": (
            "'174 BPM energy 🔥', 'When the bass drops ⚡', 'Gym PR music 💪', "
            "'Speed demon playlist 🏎️'"
        ),
    },
    "synthwave": {
        "name_vibe": "80s neon / retro-futurist invented words — chrome, sunsets, arcades, VHS",
        "name_examples": "Neonix, Chroma, Vaporis, Retrox, Miami, Vortex, Sunstrike, Cyra, Lazra, Palmyra",
        "power_words": "RETRO, NEON, 80S, NOSTALGIC, CINEMATIC, OUTRUN, DRIVING, CHROME, HYPNOTIC",
        "title_formulas": (
            "- TRACKNAME 🌴 RETRO {genre} | 80s Night Drive Mix | {genre_hashtag}\n"
            "- TRACKNAME 🌴 NEON {genre} | Outrun Banger 2026 | {genre_hashtag}\n"
            "- TRACKNAME 🌴 NOSTALGIC {genre} Track | Miami Sunset Vibes | {genre_hashtag}\n"
            "- TRACKNAME 🌴 CINEMATIC {genre} | VHS Aesthetic Mix | {genre_hashtag}"
        ),
        "thumbnail_core": (
            "An 80s retro-futurist scene: chrome sports car, palm silhouettes against a massive "
            "magenta-and-orange gridded sunset, neon horizon, VHS grain and scanlines. "
            "Palette: hot pink, electric purple, orange sun, cyan grid. Highly stylized, HIGH CONTRAST."
        ),
        "related_genres": "retrowave, outrun, darkwave, vaporwave, dreamwave, cyberpunk",
        "use_cases": "night drives, retro gaming, coding, 80s movie marathons, workout playlists",
        "tiktok_hooks": (
            "'80s night drive energy 🌴🚗', 'Outrun vibes unlocked 🕹️', 'Miami sunset mood 🌅', "
            "'Retro futurism hits different ✨'"
        ),
    },
}


def _get_genre_profile(genre: str) -> dict:
    """Return the creative profile for a genre, or a generic fallback."""
    key = (genre or "").strip().lower()
    if key in GENRE_PROFILES:
        return GENRE_PROFILES[key]
    # Try loose match (e.g. "Deep House Mix" → "deep house")
    for name, profile in GENRE_PROFILES.items():
        if name in key:
            return profile
    # Generic fallback — reuses the genre name itself, avoids forcing any aesthetic.
    return {
        "name_vibe": (
            f"short, catchy, invented words that fit the {genre} vibe — evocative, "
            "memorable, not common English words"
        ),
        "name_examples": "Axiom, Nova, Kairo, Mira, Solen, Vynn, Zara, Lumi, Orix, Kael, Nyra, Velo",
        "power_words": "ADDICTIVE, LEGENDARY, EPIC, INSANE, MASSIVE, UNREAL, HYPNOTIC, CINEMATIC, VIRAL",
        "title_formulas": (
            "- TRACKNAME 🔥 The Most ADDICTIVE {genre} Track of 2026 | Extended Mix | {genre_hashtag}\n"
            "- TRACKNAME 🔥 EPIC {genre} Drop | [Mood] Vibes | {genre_hashtag}\n"
            "- TRACKNAME 🔥 INSANE {genre} Mix | Underground Gem | {genre_hashtag}\n"
            "- TRACKNAME 🔥 The {genre} Track Everyone Is Talking About | {genre_hashtag}"
        ),
        "thumbnail_core": (
            f"A striking genre-appropriate scene that visually represents {genre} music. "
            "HIGH CONTRAST, bold colors, dramatic lighting, cinematic composition, "
            "60-70% frame focus. No text. The imagery MUST fit the mood and aesthetic of "
            f"{genre} specifically — avoid unrelated motifs."
        ),
        "related_genres": f"{genre}, electronic music, dance music",
        "use_cases": "driving, gym, festival sets, DJ mixes, playlists, chilling",
        "tiktok_hooks": (
            "'This hits different 🔥', 'Put this on repeat 🔁', 'When the drop hits 🎧', "
            "'New favorite track ✨'"
        ),
    }


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
  "youtube_description": "Write a LONG (25+ lines) description. FIRST mention this is a MEGA COMBINATION of Afro House × {secondary}. Describe the unique instruments ({instruments}). Weave in keywords naturally: afro house 2026, {secondary.lower()} music, fusion, mega combination, tribal beats, deep bass. Include use cases and a CTA. Do NOT add a standalone 'keyword cloud' or list of search terms — keywords only inside natural sentences. All keywords should say 2026 NOT 2025. Contact: imperialmediaweb@gmail.com",
  "youtube_tags": ["afro house", "{secondary.lower()} music", "afro house {secondary.lower()} fusion", "mega combination", "mega fusion", "afro house 2026", "tribal house", "deep house", "{instruments.split(',')[0].strip().lower()}", "world music fusion", "new music 2026", "best afro house 2026", "african music", "{secondary.lower()} fusion", "dj mix 2026"],
  "tiktok_caption": "MAX 150 chars. Viral hook about this INSANE fusion + hashtags #fyp #afrohouse #{secondary.lower().replace(' ', '')} #fusion #megamix",
  "thumbnail_prompt": "Generate a UNIQUE fusion artwork prompt combining African tribal aesthetics with {secondary} visual elements. The image must SCREAM 'fusion of two cultures'. GLOWING EYES, HIGH CONTRAST, dramatic lighting. No text. 4K."
}}"""



def _next_mix_number(genre: str, start: int = 8) -> int:
    """Return the next sequential "mix number" for this genre and persist it.

    Used by compilation-style title formulas (e.g. Dark House's
    "Deep House Mix • Chill / Night Vibes / Stress Relief #8"). Counter is
    stored per-genre in `output/<genre>_mix_counter.txt`; starts at `start`
    the first time, increments by 1 on every concept generation.
    """
    from config import OUTPUT_DIR
    slug = "".join(c if c.isalnum() else "_" for c in genre.lower()).strip("_") or "mix"
    counter_file = OUTPUT_DIR / f"{slug}_mix_counter.txt"
    try:
        current = int(counter_file.read_text().strip())
    except (OSError, ValueError):
        current = start
    try:
        counter_file.parent.mkdir(parents=True, exist_ok=True)
        counter_file.write_text(str(current + 1))
    except OSError as e:
        log.warning(f"Could not persist mix counter for {genre}: {e}")
    return current


def _build_system_prompt(genre: str, music_style: str) -> str:
    """Build the system prompt dynamically based on genre and style.

    The naming examples, viral title formulas, thumbnail imagery and TikTok hooks
    are ALL drawn from a per-genre profile so that e.g. Dark House does not get
    African-tribal naming or artwork, and Phonk does not get "sacred tribal"
    copy. Unknown genres fall back to a neutral profile that only keys off the
    genre name itself.
    """
    genre_lower = genre.lower().replace(" ", "")
    genre_hashtag = f"#{genre_lower}"
    profile = _get_genre_profile(genre)

    name_vibe = profile["name_vibe"]
    name_examples = profile["name_examples"]
    power_words = profile["power_words"]
    # Pass a mix_number into title_formulas so compilation-style formats
    # (e.g. Dark House "Deep House Mix • ... #8") get a fresh sequential
    # number each run. Formulas that don't reference {mix_number} ignore it.
    mix_num = _next_mix_number(genre)
    all_formulas_str = profile["title_formulas"].format(
        genre=genre,
        genre_hashtag=genre_hashtag,
        mix_number=mix_num,
    )
    # Rotate through formulas deterministically by mix_number — otherwise the
    # AI biases toward the same "WARNING: ... DANGEROUSLY Addictive" template
    # and every upload ends up with the same title.
    _formula_lines = [
        ln.lstrip("- ").strip()
        for ln in all_formulas_str.split("\n")
        if ln.strip().startswith("-")
    ]
    if _formula_lines:
        title_formulas = _formula_lines[mix_num % len(_formula_lines)]
    else:
        title_formulas = all_formulas_str
    thumbnail_core = profile["thumbnail_core"]
    related_genres = profile["related_genres"]
    use_cases = profile["use_cases"]
    tiktok_hooks = profile["tiktok_hooks"].format(genre=genre)

    world_cup_directive = ""
    if WORLD_CUP_THEME:
        world_cup_directive = (
            "\n\nWORLD CUP 2026 OVERLAY (MANDATORY — keep core genre, force this theme):\n"
            "- Music style: layer stadium chants, crowd 'oh oh oh' anthem hooks, festival "
            "drums, brass-stab build-ups and a victorious drop that feels like a goal "
            "celebration. Still 100% the underlying genre (do NOT make it pop / EDM).\n"
            "- Title MUST contain the phrase 'WORLD CUP 2026' AND 'AFRO HOUSE' literally "
            "(both in uppercase). Keep TRACKNAME, the fire emoji, the #{mix_number} pattern "
            "and {genre_hashtag} from the formula. Example shape: "
            "'TRACKNAME 🔥 WORLD CUP 2026 AFRO HOUSE ANTHEM • Stadium Energy #{mix_number} "
            "| {genre_hashtag}'. Stay under 100 chars.\n"
            "- Description: the FIRST sentence MUST contain the exact phrase "
            "'World Cup 2026 Afro House' and frame the track as a stadium anthem / "
            "pre-game hype / goal-celebration drop. Mention football, fans, terraces, "
            "anthems naturally — no fake claims about official tournament affiliation, "
            "no team names, no FIFA branding.\n"
            "- Hashtags: include #worldcup2026 #worldcup #fifa2026 #footballanthem "
            "#stadiumvibes alongside the genre tags. Keep total count within 10-15.\n"
            "- TikTok caption: MUST start with a football/World Cup hook (e.g. 'POV: "
            "stadium 90th min and this drops 🏆⚽🔥', 'Afro House World Cup 2026 anthem'). "
            "Always include #fyp #worldcup2026 #afrohouse.\n"
            "- Thumbnail (visual consistency across ALL tracks): SAME framing every time — "
            "central bold subject (African mask or warrior/queen portrait) lit from one "
            "side, dark stadium silhouette behind, terrace lights as bokeh, raised flag "
            "shapes (no real flags), confetti or pyro burst. Palette: deep gold + black + "
            "ember orange. No team logos, no real player faces, no FIFA marks, no text.\n"
        )

    return f"""You are a creative {genre} music producer and YouTube SEO expert.
Generate a unique {genre} track concept. The track style is:
{music_style}{world_cup_directive}

IMPORTANT NAMING RULE:
- The track_name MUST be 1-2 short, catchy, invented words that fit the {genre} vibe.
- Specifically: {name_vibe}.
- They should sound memorable but NOT be common English words, and NOT be generic.
- Do NOT reuse names from previous tracks.
- CRITICAL: Vary the starting letter EVERY TIME across the WHOLE alphabet — A, B, C, D, E, F, G, H, I, J, K, L, M, N, O, P, Q, R, S, T, U, V, W, X, Y, Z. Do NOT always start with the same letter.
- Examples of good names for THIS genre: {name_examples}.
- The name MUST evoke the aesthetic of {genre} specifically. Do NOT force aesthetics from unrelated genres.

CRITICAL: Every track MUST have a COMPLETELY DIFFERENT youtube_title, youtube_description, thumbnail_prompt and tiktok_caption.
- Do NOT reuse phrases, adjectives, metaphors or imagery from previous tracks.
- Vary the structure, wording, and sentence patterns each time.
- All creative choices (names, titles, covers, hooks) MUST be specific to the {genre} genre — no generic or off-genre motifs.

Everything (youtube_title, youtube_description, hashtags, youtube_tags, tiktok_caption, thumbnail_prompt) MUST be in English.

Return ONLY valid JSON with these exact fields:

{{
  "track_name": "1-2 invented catchy words that fit the {genre} vibe — see name rules above",
  "mood": "emotional mood/vibe — pick something UNIQUE each time and appropriate to {genre} (e.g. euphoric, hypnotic, volcanic, celestial, nocturnal, cinematic, dreamy, aggressive, ethereal, melancholic, sultry, relentless)",
  "description": "2-3 sentence vivid description of the track's atmosphere and energy, specific to the {genre} aesthetic (in English)",
  "music_prompt": "detailed prompt for AI music generation - describe instruments, rhythm, bass, mood, style. Must match the {genre} genre specifically.",
  "lyrics": "Song lyrics in English, formatted with standard section tags like [Verse 1], [Chorus], [Verse 2], [Bridge], [Outro]. Keep it tight: 1-2 short verses + catchy chorus + optional bridge, roughly 150-350 words total. Theme and vocal style MUST fit the {genre} aesthetic (e.g. Dark House = soft breathy female vocals, love/night/neon/emotional themes). If the genre is traditionally instrumental (e.g. Afro House), return an empty string and the track will be instrumental.",
  "hashtags": ["10-15 hashtags RELEVANT TO {genre} — mix genre-specific and general music hashtags. Do NOT include hashtags from unrelated genres."],
  "youtube_title": "Use EXACTLY this title formula, replacing TRACKNAME with the actual UPPERCASE track name:\\n\\n{title_formulas}\\n\\nSEO KEYWORD RULES:\\n1. Keep the genre name '{genre}' from the formula intact (critical for search ranking)\\n2. Do NOT add power words beyond what's already in the formula\\n3. Do NOT rewrite or paraphrase the formula — only substitute TRACKNAME\\n4. If a year is in the formula keep it as 2026\\n5. Output MUST stay under 100 chars total\\n6. Do NOT include duration\\n\\nRules: track name UPPERCASE, fire emoji after name, end with {genre_hashtag}.",
  "youtube_description": "Write a LONG (25+ lines) YouTube description FULLY OPTIMIZED for YouTube SEO and algorithm recommendations.\\n\\nSTRUCTURE (follow this order):\\n\\n1. FIRST 2 LINES (most important — shown in search results before 'Show more'):\\n   - Include the EXACT track name and the genre '{genre}' in the first sentence\\n   - Use high-search keywords specific to {genre} and related genres: {related_genres}\\n   - Make it compelling enough to click 'Show more'\\n\\n2. KEYWORD-RICH BODY (5-8 lines):\\n   - Describe the track's sound, instruments, energy, and atmosphere in a way that fits {genre}\\n   - Naturally weave in SEARCH KEYWORDS relevant to {genre}: {related_genres}\\n   - Each sentence should contain at least one searchable keyword\\n\\n3. USE CASES with keywords (3-4 lines):\\n   - 'Perfect for: [keyword-rich list relevant to {genre}]' — e.g. {use_cases}\\n   - This helps YouTube match your video to DIFFERENT search queries\\n\\n4. CALL TO ACTION (2-3 lines):\\n   - Ask viewers to LIKE, SUBSCRIBE, and turn on NOTIFICATIONS\\n   - Ask them to COMMENT their favorite part\\n   - Ask them to SHARE with friends who love {genre}\\n\\n5. CONTACT: imperialmediaweb@gmail.com\\n\\nIMPORTANT RULES:\\n- Do NOT include a 'Keyword Cloud' or any standalone list of search terms — that looks like keyword stuffing and is added separately. Keywords must only appear woven naturally into sentences.\\n- Do NOT include hashtags (#) in the description (they get added separately)\\n- Do NOT reference aesthetics from unrelated genres (no African/tribal talk unless the genre IS Afro House, no neon/rain talk unless the genre IS Dark House, etc.)\\n- EVERY sentence should be keyword-rich but still read naturally\\n- VARY the structure, wording, and keywords each time — no two descriptions should be similar\\n- Use line breaks and spacing for readability",
  "youtube_tags": ["Generate 25-30 YouTube tags OPTIMIZED for search discovery, ALL relevant to {genre}.\\n\\nINCLUDE THESE TAG CATEGORIES:\\n\\n1. EXACT MATCH genre tags (highest priority):\\n   '{genre}', '{genre} music', '{genre} mix', '{genre} 2026', 'new {genre}', 'best {genre}'\\n\\n2. RELATED genre tags (only those that genuinely fit {genre}): {related_genres}\\n\\n3. MOOD/VIBE tags that fit {genre} specifically\\n\\n4. USE CASE tags: {use_cases}\\n\\n5. TRENDING/DISCOVERY tags: 'new music 2026', 'music mix 2026', 'best music 2026', 'trending music', 'viral music'\\n\\n6. TRACK-SPECIFIC tags: include the track name as a tag\\n\\nRULES: Each tag max 100 chars, total under 500 chars. Mix short (1-2 word) and long-tail (3-4 word) tags. NO hashtag symbols. Do NOT include tags for unrelated genres."],
  "tiktok_caption": "Write a VIRAL TikTok caption optimized for TikTok's For You Page (FYP). MAX 150 chars.\\n\\nFORMULA: [Viral hook specific to {genre}] + [3-5 strategic hashtags]\\n\\nGENRE-SPECIFIC HOOKS (pick one, vary each time): {tiktok_hooks}\\n\\nHASHTAG STRATEGY:\\n- ALWAYS include: #fyp #foryou\\n- Genre: #{genre_lower} plus related hashtags for {genre} only (do NOT tag unrelated genres)\\n- Trending: #newmusic #viralmusic #musicdiscovery\\n\\nPick 3-5 hashtags that fit within the 150 char limit. Always include #fyp.",
  "thumbnail_prompt": "Generate a UNIQUE image prompt for a YouTube thumbnail that FITS the {genre} genre specifically.\\n\\nCORE AESTHETIC for {genre}:\\n{thumbnail_core}\\n\\nSTYLE RULES (MANDATORY):\\n1. STYLE: oil painting, hyper-realistic fine art, or photorealistic portrait — like a museum masterpiece\\n2. WARM NATURAL TONES: deep brown, bronze, gold, amber, ochre, burnt sienna, copper — NO neon, NO electric blue, NO sci-fi colors\\n3. ONE bold focal point (mask or face portrait) fills 60-70% of the frame, CENTERED\\n4. DRAMATIC LIGHTING: warm side light like a Renaissance/Caravaggio painting — NO lasers, NO glowing eyes, NO particle effects\\n5. BACKGROUND: warm dark tones (deep brown, dark amber, umber) — NOT pure black\\n6. TEXTURES: real carved wood grain, natural materials (cowrie shells, bone beads, feathers, raffia, brass)\\n7. MOOD: sacred, ancestral, spiritual, warm — like a ritual artifact photographed in a museum\\n\\nFORBIDDEN: neon glow, glowing eyes, sci-fi effects, lasers, modern elements, flat illustration style, cartoon, minimalist design, CGI look\\n\\nCRITICAL: Each thumbnail must be COMPLETELY different from any previous one. No text. 4K ultra detailed."
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
    _genre_key = genre.strip().lower()
    # Only use the Afro House music/thumbnail defaults when the genre IS Afro House.
    # For any other genre, fall back to the per-genre profile so we don't leak
    # tribal/African motifs into e.g. Dark House or Phonk outputs.
    if _genre_key == "afro house":
        music_style = music_style or MUSIC_STYLE_PROMPT or DEFAULT_AFRO_HOUSE_STYLE
        thumbnail_style = thumbnail_style or THUMBNAIL_STYLE_PROMPT or DEFAULT_THUMBNAIL_PROMPT
    else:
        _profile = _get_genre_profile(genre)
        music_style = music_style or MUSIC_STYLE_PROMPT or (
            f"Create a {genre} track that fully fits the {genre} genre aesthetic. "
            "Describe instruments, rhythm, tempo, bass, mood and production style faithful to the genre."
        )
        thumbnail_style = thumbnail_style or THUMBNAIL_STYLE_PROMPT or _profile["thumbnail_core"]

    log.info(f"Generating {genre} music concept...")

    client = OpenAI(api_key=OPENAI_API_KEY)

    system_prompt = _build_system_prompt(genre, music_style)

    user_msg = (
        f"Generate a fresh, original {genre} track concept. "
        f"The track name MUST be an invented catchy word (or two) that fits the {genre} aesthetic — "
        "NOT common English words, and NOT a vibe from an unrelated genre. "
        "IMPORTANT: Start the name with a DIFFERENT letter each time — vary across the whole alphabet. "
        "Title, thumbnail, description, hashtags and TikTok caption must ALL be specific to "
        f"{genre} (no tribal/African motifs unless the genre is Afro House). "
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
    # Genre-appropriate fallback name (first example from the profile)
    _fallback_name = _get_genre_profile(genre)["name_examples"].split(",")[0].strip()
    final_name = data.get("track_name", _fallback_name)
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
        lyrics=data.get("lyrics", "") or "",
    )
