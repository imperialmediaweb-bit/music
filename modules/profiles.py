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
    },

    "gym": {
        "label": "Gym Workout",
        "hybrid": True,
        "fresh_count": 4,
        "archive_count": 4,
        "archive_min_pool": 12,
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
    },

    "driving": {
        "label": "Driving",
        "hybrid": True,
        "fresh_count": 4,
        "archive_count": 6,
        "archive_min_pool": 12,
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
    },

    "focus": {
        "label": "Focus & Study",
        "hybrid": True,
        "fresh_count": 4,
        "archive_count": 4,
        "archive_min_pool": 12,
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
    },

    "meditation": {
        "label": "Meditation",
        "hybrid": True,
        "fresh_count": 4,
        "archive_count": 4,
        "archive_min_pool": 12,
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
