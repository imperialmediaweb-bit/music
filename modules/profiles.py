"""Playlist profiles — each defines music style, thumbnail, tags, duration,
and YouTube playlists for a specific audience niche (Gym, Driving, Focus, etc.).

The weekly plan maps each day of the week to a profile so the scheduler
automatically targets a different niche each upload day.
"""

import os
import random
from datetime import datetime


PLAYLIST_PROFILES = {
    "main": {
        "label": "Afro House",
        "hybrid": True,
        "fresh_count": 4,
        "archive_count": 4,
        "archive_min_pool": 12,
        "title_suffixes": [],
        "suno_prompt_addition": (
            "IMMEDIATE DROP in first 5 seconds, NO slow intro, "
            "powerful percussion from second zero, hypnotic repetition, "
            "full mix energy, classic tribal afro house, deep bass, spiritual groove"
        ),
        "thumbnail_style_variants": [
            "oil painting of an authentic African tribal mask, carved dark wood with rich patina, cowrie shells and bone beads, warm amber side lighting, deep brown background, sacred ancestral mood, hyper-realistic, no text, 4K",
            "photorealistic African face portrait with closed eyes, tribal scarification dots, woven geometric halo headdress, warm golden-brown tones, Renaissance painting lighting, no text, 4K",
            "hyper-realistic Dogon ceremonial mask, intricate wood carvings, natural feathers and raffia fiber, brass ornaments, warm ochre and bronze tones, dark umber background, museum-quality oil painting, no text, 4K",
            "realistic African ancestral mask with geometric patterns, copper and gold inlays, cowrie shell crown, warm dramatic candlelight, deep brown atmosphere, fine art style, no text, 4K",
            "oil painting of a Yoruba ritual mask, polished dark wood, beaded crown with natural stones, tribal face paint in ochre and white kaolin, warm amber lighting, sacred spiritual mood, no text, 4K",
        ],
        "extra_tags": [
            "afrohouse", "deephouse", "tribalhouse", "africanmusic",
            "deepafrohouse", "groovegenix", "spiritualhouse",
        ],
        "description_intro": (
            "Deep Afro House with tribal grooves and ritual energy. "
            "Perfect for any moment you need powerful rhythm."
        ),
        "youtube_playlists": ["Afro House"],
        "crossfade_sec": 0,
        "video_comments": [
            "🔥 Drop a 🙌 if this beat hits your soul! Which part gave you chills? Comment the timestamp!\n\n👉 Subscribe & turn on 🔔 for daily Afro House mixes — share this with someone who needs it!",
            "💬 What's YOUR favorite moment in this track? Drop the timestamp below!\n\n🎧 Hit Subscribe + 🔔 so you never miss a new mix. Share this vibe with a friend!",
            "🎶 This one's different. Can you feel it? Tell me your favorite part in the comments!\n\n👉 Subscribe for more deep Afro House every day. Share if this track moved you! 🙌",
        ],
        "short_comments": [
            "🔥 Full track on the channel — go listen NOW! Drop a ❤️ if you felt this\n\n👉 Subscribe + 🔔 for daily vibes!",
            "💥 This is just a taste — full mix on our channel! Subscribe & share with someone who needs this energy 🎧",
            "🎵 Want more? Full track is UP! Hit Subscribe + 🔔 and never miss a beat. Share this with a friend! 🔥",
        ],
    },

    "gym": {
        "label": "Gym Workout",
        "hybrid": True,
        "fresh_count": 4,
        "archive_count": 8,
        "archive_min_pool": 12,
        "title_suffixes": [
            "| You'll Train HARDER With This", "| BEAST MODE Activated",
            "| Your New Gym Obsession", "| Warning: PR Incoming",
            "| The Gym Mix Everyone's Talking About", "| Lift Heavy To This",
        ],
        "suno_prompt_addition": (
            "powerful bass, driving tribal drums, high energy, 128 BPM, "
            "aggressive percussion, motivational workout vibe, "
            "IMMEDIATE DROP in first 5 seconds, NO slow intro, "
            "relentless groove, gym training energy, pushing harder, "
            "intense rhythm throughout"
        ),
        "thumbnail_style_variants": [
            "oil painting of a fierce African warrior mask, carved hardwood with battle scars, red ochre war paint, bone and iron ornaments, warm firelight, deep dark brown background, hyper-realistic, no text, 4K",
            "photorealistic Chokwe battle mask, angular aggressive carvings, copper studs and animal teeth, warm red-bronze tones, dramatic side lighting like a Caravaggio painting, no text, 4K",
            "hyper-realistic tribal war mask with sharp geometric patterns, iron and brass details, raffia mane, intense warm ember lighting, dark umber background, museum oil painting style, no text, 4K",
            "oil painting of an ancient African warrior face with ritual scars, tribal crown of feathers and bone, red and brown earth tones, powerful sacred mood, Renaissance chiaroscuro lighting, no text, 4K",
        ],
        "extra_tags": [
            "gymmusic", "workoutmusic", "trainingmusic",
            "cardiomusic", "gymmotivation", "workoutmix", "gymbeats",
        ],
        "description_intro": (
            "Powerful Afro House for your most intense workouts. "
            "Deep bass, tribal drums, relentless energy for gym training, "
            "cardio, lifting and strength sessions. Push harder, train with rhythm."
        ),
        "youtube_playlists": ["Afro House", os.getenv("YT_PLAYLIST_GYM_NAME", "Gym Workout Mix")],
        "crossfade_sec": 3,
        "video_comments": [
            "💪 Tag your gym partner who NEEDS this playlist! Drop a 🔥 if you're training to this right now!\n\n👉 Subscribe + 🔔 for weekly workout mixes. Share this with your gym crew!",
            "🏋️ What's your PR while listening to this? Drop it in the comments!\n\n🎧 Subscribe for more gym beats — share this with someone who lifts heavy! 💪",
            "⚡ This beat = BEAST MODE. Drop a 💪 if you trained to this!\n\n👉 Hit Subscribe + 🔔 for new workout mixes. Send this to your training partner!",
        ],
        "short_comments": [
            "💪 Full workout mix on the channel — go crush your session! Drop a 🔥\n\n👉 Subscribe + 🔔 for gym beats!",
            "🏋️ Just a preview — full mix is UP! Subscribe & share with your gym crew! 💪",
            "⚡ BEAST MODE activated. Full track on our channel! Subscribe + share! 🔥",
        ],
    },

    "driving": {
        "label": "Driving",
        "hybrid": True,
        "fresh_count": 4,
        "archive_count": 12,
        "archive_min_pool": 12,
        "title_suffixes": [
            "| Perfect For Late Night Drives", "| Your Car Will SHAKE",
            "| The Ultimate Night Drive Mix", "| Windows Down, Bass UP",
            "| You'll Never Drive In Silence Again", "| Highway Hypnosis",
        ],
        "suno_prompt_addition": (
            "hypnotic steady groove, deep bass, continuous flow, 122 BPM, "
            "cinematic night atmosphere, NO sudden drops, "
            "immersive driving rhythm, smooth transitions, "
            "IMMEDIATE hook in first 5 seconds, long sustained energy, "
            "car bass, sub-bass impact"
        ),
        "thumbnail_style_variants": [
            "oil painting of a serene African mask, carved dark wood with smooth finish, deep indigo and midnight blue tones, soft moonlight glow, warm brown background, contemplative mood, hyper-realistic, no text, 4K",
            "photorealistic Baule mask with polished wood grain, subtle blue-bronze patina, cowrie shells, warm night atmosphere with deep amber and indigo, fine art painting style, no text, 4K",
            "hyper-realistic African ancestral mask, dark mahogany wood, turquoise stone inlays, brass wire details, warm golden-blue twilight tones, oil painting style, no text, 4K",
            "oil painting of a mysterious Fang mask, sleek dark wood with bronze highlights, deep warm tones with hints of blue, sacred night ritual mood, Renaissance lighting, no text, 4K",
        ],
        "extra_tags": [
            "drivingmusic", "nightdrive", "roadtripmusic",
            "cruising", "longmix", "nightvibes", "carbass",
        ],
        "description_intro": (
            "Long Afro House mixes for night drives and road trips. "
            "Steady groove, deep bass, hypnotic rhythms to keep you in the zone. "
            "Perfect for highway driving, late-night cruising, long-distance trips."
        ),
        "youtube_playlists": ["Afro House", os.getenv("YT_PLAYLIST_DRIVING_NAME", "Driving Music")],
        "crossfade_sec": 3,
        "video_comments": [
            "🚗 Where are you driving to with this? Drop your city below!\n\n👉 Subscribe + 🔔 for night drive mixes every week. Share this with your road trip crew! 🌙",
            "🌃 Night drive vibes on another level. Comment your favorite road trip song!\n\n🎧 Subscribe for more driving playlists — share this with someone who drives late! 🚗",
            "🛣️ This + open road = perfection. Tag someone you'd road trip with!\n\n👉 Hit Subscribe + 🔔 for weekly driving mixes. Share the vibes! 🌙",
        ],
        "short_comments": [
            "🚗 Full night drive mix on the channel — perfect for the road! Drop a 🌙\n\n👉 Subscribe + 🔔!",
            "🌃 Just a taste — full driving mix is UP! Subscribe & share with your road trip partner! 🚗",
            "🛣️ Open road + this beat = magic. Full mix on our channel! Subscribe! 🌙",
        ],
    },

    "focus": {
        "label": "Focus & Study",
        "hybrid": True,
        "fresh_count": 4,
        "archive_count": 8,
        "archive_min_pool": 12,
        "title_suffixes": [
            "| You'll Focus Like NEVER Before", "| Productivity On Another Level",
            "| The Study Mix That Actually Works", "| Enter Flow State NOW",
            "| Your Brain Will Thank You", "| Deep Work Mode: ON",
        ],
        "suno_prompt_addition": (
            "minimal instrumental, hypnotic repetition, 118 BPM, "
            "no vocals or very distant vocals only, "
            "deep and immersive, background-friendly, "
            "no distracting elements, meditative flow but rhythmic, "
            "gentle entry in first 5 seconds but present from start"
        ),
        "thumbnail_style_variants": [
            "oil painting of a serene African face portrait with closed eyes, tribal dots on cheeks, smooth skin, woven circular halo, warm golden-brown tones, soft ambient light, peaceful sacred mood, no text, 4K",
            "hyper-realistic Punu mask with smooth white kaolin finish, delicate scarification lines, calm expression, warm ochre and cream tones, soft Renaissance lighting, museum oil painting, no text, 4K",
            "photorealistic African meditation mask, polished light wood, minimalist geometric patterns, gentle warm amber glow, deep brown background, serene contemplative mood, fine art style, no text, 4K",
            "oil painting of an elegant Baule portrait mask, smooth curved features, subtle gold leaf accents, warm earth tones, soft candlelight, tranquil spiritual atmosphere, no text, 4K",
        ],
        "extra_tags": [
            "focusmusic", "studymusic", "workmusic",
            "concentration", "backgroundmusic", "instrumentalmix", "codingmusic",
        ],
        "description_intro": (
            "Deep Afro House for work, study and concentration. "
            "Hypnotic instrumental grooves to help you focus on deep work, "
            "coding, writing, studying or creative tasks without distraction."
        ),
        "youtube_playlists": ["Afro House", os.getenv("YT_PLAYLIST_FOCUS_NAME", "Focus & Study Music")],
        "crossfade_sec": 5,
        "video_comments": [
            "🧠 What are you working on right now? Drop it below!\n\n👉 Subscribe + 🔔 for daily focus & study music. Share this with someone who needs deep concentration! 📚",
            "💻 Coding? Studying? Writing? This is YOUR soundtrack. Comment what you're grinding on!\n\n🎧 Subscribe for more focus playlists — share with a friend who works hard! 🧠",
            "📚 Put this on, zone in, and GO. What are you focusing on today? Tell me below!\n\n👉 Subscribe + 🔔 for weekly study mixes. Share with your study crew! 💻",
        ],
        "short_comments": [
            "🧠 Full focus mix on the channel — perfect for deep work! Drop a 💻\n\n👉 Subscribe + 🔔!",
            "📚 Just a preview — full study mix is UP! Subscribe & share with your study group! 🧠",
            "💻 Zone in. Full mix on our channel! Subscribe + share with someone who grinds! 📚",
        ],
    },

    "meditation": {
        "label": "Meditation",
        "hybrid": True,
        "fresh_count": 4,
        "archive_count": 8,
        "archive_min_pool": 12,
        "title_suffixes": [
            "| Fall Asleep In Minutes", "| Instant Calm Guaranteed",
            "| The Most Peaceful Mix You'll Ever Hear", "| Breathe And Let Go",
            "| Your Mind Will Thank You", "| Pure Healing Energy",
        ],
        "suno_prompt_addition": (
            "ambient tribal, soft percussion, warm atmospheric pads, 100 BPM, "
            "NO harsh elements, breathwork-friendly, yoga-appropriate, "
            "deeply calming, spacious, meditative entry, "
            "soft but present from second zero, hypnotic and introspective"
        ),
        "thumbnail_style_variants": [
            "oil painting of a spiritual African healing mask, warm wood with golden patina, natural feathers and dried flowers, soft sunset amber light, warm earth tone background, peaceful ancestral mood, no text, 4K",
            "photorealistic African face portrait with closed eyes and peaceful smile, ritual ochre dots, woven grass crown, warm honey and brown tones, soft glowing light, fine art oil painting, no text, 4K",
            "hyper-realistic ceremonial Songye mask, smooth carved wood, cowrie shell details, feather headdress, warm candlelight glow, deep brown background, sacred healing atmosphere, no text, 4K",
            "oil painting of a Makonde spirit mask, organic flowing wood grain, subtle earth-tone pigments, natural fibers, warm golden hour lighting, serene meditative mood, museum quality, no text, 4K",
        ],
        "extra_tags": [
            "meditationmusic", "yogamusic", "relaxation",
            "mindfulness", "tribalambient", "ambienthouse", "sleepmusic",
        ],
        "description_intro": (
            "Deep Afro House and ambient Tribal House for relaxation, "
            "meditation and mindfulness. Slow grooves, soft tribal percussion, "
            "warm bass and hypnotic rhythms to calm the mind and release stress."
        ),
        "youtube_playlists": ["Afro House", os.getenv("YT_PLAYLIST_MEDITATION_NAME", "Meditation & Healing")],
        "crossfade_sec": 5,
        "video_comments": [
            "🧘 Take a deep breath. How do you feel right now? Share below!\n\n👉 Subscribe + 🔔 for meditation & healing music. Share this with someone who needs peace! 🙏",
            "🌅 Close your eyes, breathe, and let go. What does this track make you feel? Comment below!\n\n🎧 Subscribe for weekly meditation mixes — share with someone who deserves calm! 🧘",
            "🙏 This is your moment of peace. Tag someone who needs to hear this today!\n\n👉 Subscribe + 🔔 for healing vibes. Share the calm! 🌅",
        ],
        "short_comments": [
            "🧘 Full meditation mix on the channel — breathe and relax! Drop a 🙏\n\n👉 Subscribe + 🔔!",
            "🌅 Just a moment of calm — full mix is UP! Subscribe & share peace with someone! 🧘",
            "🙏 Need more calm? Full track on our channel! Subscribe + share healing vibes! 🌅",
        ],
    },
}


WEEKLY_PLAN = {
    0: "main",        # Luni
    1: "gym",         # Marți
    2: "main",        # Miercuri
    3: "focus",       # Joi
    4: "driving",     # Vineri
    5: "main",        # Sâmbătă
    6: "meditation",  # Duminică
}


def get_todays_profile():
    """Return (profile_name, profile_dict) for today based on WEEKLY_PLAN."""
    day = datetime.now().weekday()
    name = WEEKLY_PLAN[day]
    return name, PLAYLIST_PROFILES[name]


def get_random_thumbnail_style(profile):
    """Pick a random thumbnail style variant from the profile."""
    variants = profile.get("thumbnail_style_variants", [])
    if variants:
        return random.choice(variants)
    return ""
