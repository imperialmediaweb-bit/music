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
        "archive_count": 2,
        "archive_min_pool": 12,
        "title_suffixes": [],
        "suno_prompt_addition": (
            "IMMEDIATE DROP in first 5 seconds, NO slow intro, "
            "powerful percussion from second zero, hypnotic repetition, "
            "full mix energy, classic tribal afro house, deep bass, spiritual groove"
        ),
        "thumbnail_style_variants": [
            "tribal mask with glowing eyes, mystical atmosphere, dark cinematic background",
            "silhouette of dancer with colorful concert lights, energetic mood",
            "stylized African landscape at night with campfire and acacia trees",
            "bold typography design with large track name, minimal imagery, solid accent color",
            "close-up traditional African instruments (djembe, kora) with dramatic lighting",
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
        "archive_count": 4,
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
            "silhouette of athlete in motion with tribal elements, intense lighting",
            "tribal warrior mask with glowing red energy effects, powerful atmosphere",
            "abstract explosion of energy with tribal drums, motion blur",
            "bold typography 'GYM BEATS' with aggressive design, red and black",
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
        "archive_count": 6,
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
            "night road with headlights, highway, city lights in distance, cinematic",
            "car on empty highway at night with tribal mask in sky reflection",
            "dashboard view at night with starry sky and subtle tribal elements",
            "bold 'NIGHT DRIVE' typography with road and lights theme",
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
        "archive_count": 4,
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
            "minimal abstract geometric tribal pattern, clean design, muted palette",
            "subtle tribal mask in soft focus with gentle lighting",
            "zen workspace with tribal elements, calm professional aesthetic",
            "typography 'DEEP FOCUS' with minimal tribal accents, muted colors",
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
        "archive_count": 4,
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
            "serene natural landscape (sunset, lake, mountain) with stylized tribal mask",
            "peaceful meditation scene with soft tribal elements, golden hour light",
            "abstract spiritual imagery with warm pastel palette",
            "typography 'MEDITATION' with nature and tribal blend, soft colors",
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
