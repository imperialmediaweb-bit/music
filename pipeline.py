import json
import subprocess
from pathlib import Path

from utils.logger import log
from utils.auto_setup import ensure_path
from modules.concept_generator import generate_concept
from modules.thumbnail_generator import generate_thumbnail, generate_cover_art, generate_thumbnail_and_cover
from modules.video_creator import create_video, create_short_video, generate_chapters
from modules.youtube_uploader import upload_to_youtube, post_comment
from modules.tiktok_uploader import upload_to_tiktok
from modules.tunecore_uploader import upload_to_tunecore
from modules.soundcloud_uploader import upload_to_soundcloud
from modules.bandcamp_uploader import upload_to_bandcamp
from config import SKIP_TUNECORE, SKIP_SOUNDCLOUD, SKIP_TIKTOK, SKIP_BANDCAMP

# Default artist name (used for cover art overlay and TuneCore metadata)
DEFAULT_ARTIST = "GrooveGenix"


def reupload_track(track_name: str, only: str | None = None) -> dict:
    """Re-upload an existing track to YouTube and TikTok (skip generation/video steps).

    Looks for existing files in OUTPUT_DIR:
      - {track_name}_video.mp4
      - {track_name}_thumbnail.jpg (or .png for older tracks)
      - {track_name}.mp3  (for duration detection)

    Regenerates concept metadata (title, description, tags) via OpenAI,
    then uploads to both platforms.
    """
    ensure_path()
    from config import OUTPUT_DIR
    from modules.concept_generator import generate_concept

    result = {
        "concept": track_name,
        "duration": None,
        "youtube_url": None,
        "tiktok_url": None,
        "tunecore_url": None,
        "bandcamp_url": None,
        "soundcloud_url": None,
        "errors": [],
    }

    # Locate existing files — check multiple naming conventions
    video = None
    for suffix in ["_video.mp4", "_tiktok.mp4", ".mp4"]:
        candidate = OUTPUT_DIR / f"{track_name}{suffix}"
        if candidate.exists():
            video = candidate
            break
    # Check both .jpg (new) and .png (old) thumbnail formats
    thumbnail = OUTPUT_DIR / f"{track_name}_thumbnail.jpg"
    if not thumbnail.exists():
        thumbnail = OUTPUT_DIR / f"{track_name}_thumbnail.png"
    mp3_file = OUTPUT_DIR / f"{track_name}.mp3"

    if not thumbnail.exists():
        log.warning(f"Thumbnail not found: {thumbnail} — continuing without it")

    if not video and only != "tunecore":
        log.error(f"Video not found in output/ (tried _video.mp4, _tiktok.mp4, .mp4)")
        result["errors"].append(f"missing: {track_name} video in {OUTPUT_DIR}")
        return result

    if video:
        log.info(f"Found video: {video}")

    # Detect duration from MP3 (if available)
    duration_sec = 0
    if mp3_file.exists():
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", str(mp3_file)],
                capture_output=True, text=True,
            )
            duration_sec = float(json.loads(probe.stdout)["format"]["duration"])
            result["duration"] = _format_duration(duration_sec)
            log.info(f"Duration: {result['duration']}")
        except Exception:
            log.warning("Could not detect duration — continuing without it")

    # Generate fresh concept metadata
    log.info("=" * 60)
    log.info(f"Generating concept metadata for '{track_name}'...")
    concept = generate_concept(track_name=track_name)

    # Inject duration into title (same logic as process_single_track)
    if duration_sec:
        duration_mins = int(duration_sec) // 60
        if "\U0001f525" in concept.youtube_title:
            concept.youtube_title = concept.youtube_title.replace(
                "\U0001f525", f"\U0001f525 {duration_mins} Minutes of", 1
            )
        concept.youtube_title = concept.youtube_title[:100]
        concept.youtube_description = concept.youtube_description.replace(
            "{duration}", str(duration_mins)
        )
        concept.youtube_description += f"\n\nDuration: {result['duration']}"

    log.info(f"YouTube title: {concept.youtube_title}")

    # Upload to YouTube
    if only in (None, "youtube"):
        try:
            log.info("=" * 60)
            log.info("Uploading to YouTube...")
            youtube_url = upload_to_youtube(video, thumbnail, concept)
            result["youtube_url"] = youtube_url
            if youtube_url:
                log.info(f"YouTube URL: {youtube_url}")
            else:
                log.error("YouTube upload returned None — check client_secrets.json and OAuth token")
                result["errors"].append("youtube: upload returned None (check client_secrets.json / OAuth)")
        except Exception as e:
            log.error(f"YouTube upload failed: {e}")
            result["errors"].append(f"youtube: {e}")
    else:
        log.info(f"Skipping YouTube (--only {only})")

    # Upload to TikTok
    if SKIP_TIKTOK:
        log.info("=" * 60)
        log.info("TikTok SKIPPED (SKIP_TIKTOK=true)")
    elif only in (None, "tiktok"):
        try:
            log.info("=" * 60)
            log.info("Uploading to TikTok...")
            tiktok_url = upload_to_tiktok(video, concept)
            result["tiktok_url"] = tiktok_url
            if tiktok_url:
                log.info(f"TikTok: {tiktok_url}")
            else:
                log.error("TikTok upload returned None — check cookies/login above")
                result["errors"].append("tiktok: upload returned None (cookies expired or login redirect)")
        except Exception as e:
            log.error(f"TikTok upload failed: {e}")
            result["errors"].append(f"tiktok: {e}")
    else:
        log.info(f"Skipping TikTok (--only {only})")

    # Upload to TuneCore (always runs with youtube/tiktok too)
    if only in (None, "tunecore", "youtube", "tiktok"):
        # Files may use underscores instead of spaces (audio_merger convention)
        name_variants = [track_name, track_name.replace(" ", "_")]
        wav_file = None
        for name in name_variants:
            candidate = OUTPUT_DIR / f"{name}.wav"
            if candidate.exists():
                wav_file = candidate
                break
        # Fallback: pick the most recently modified WAV in output/
        if not wav_file:
            all_wavs = sorted(OUTPUT_DIR.glob("*.wav"), key=lambda f: f.stat().st_mtime, reverse=True)
            all_wavs += sorted(OUTPUT_DIR.glob("*.WAV"), key=lambda f: f.stat().st_mtime, reverse=True)
            if all_wavs:
                wav_file = all_wavs[0]
                log.info(f"WAV not found by name — using latest: {wav_file}")

        # Look for existing cover art
        cover_file = None
        for name in name_variants:
            for suffix in ["_cover.jpg", "_cover.png"]:
                candidate = OUTPUT_DIR / f"{name}{suffix}"
                if candidate.exists():
                    cover_file = candidate
                    break
            if cover_file:
                break

        if not wav_file:
            log.warning(f"WAV file not found in {OUTPUT_DIR} — skipping TuneCore")
            result["errors"].append(f"tunecore: WAV not found in {OUTPUT_DIR}")
        elif not cover_file:
            # Generate cover art if missing
            try:
                log.info("=" * 60)
                log.info("Generating 1600x1600 cover art for TuneCore...")
                cover_file = generate_cover_art(
                    concept.thumbnail_prompt, concept.track_name, DEFAULT_ARTIST
                )
                log.info(f"Cover art: {cover_file}")
            except Exception as e:
                log.error(f"Cover art generation failed: {e}")
                result["errors"].append(f"cover_art: {e}")

        if wav_file and cover_file:
            try:
                log.info("=" * 60)
                log.info("Uploading to TuneCore...")
                tunecore_url = upload_to_tunecore(wav_file, cover_file, concept)
                result["tunecore_url"] = tunecore_url
                if tunecore_url:
                    log.info(f"TuneCore: {tunecore_url}")
                else:
                    log.error("TuneCore upload returned None — run: python main.py tunecore-login")
                    result["errors"].append("tunecore: upload returned None (session expired)")
            except Exception as e:
                log.error(f"TuneCore upload failed: {e}")
                result["errors"].append(f"tunecore: {e}")
    else:
        log.info(f"Skipping TuneCore (--only {only})")

    # Upload to Bandcamp (right after TuneCore)
    if only in (None, "bandcamp"):
        if SKIP_BANDCAMP:
            log.info("Skipping Bandcamp (SKIP_BANDCAMP=true)")
        else:
            name_variants = [track_name, track_name.replace(" ", "_")]
            bc_wav = None
            for name in name_variants:
                candidate = OUTPUT_DIR / f"{name}.wav"
                if candidate.exists():
                    bc_wav = candidate
                    break
            bc_cover = None
            for name in name_variants:
                for suffix in ["_cover.jpg", "_cover.png"]:
                    candidate = OUTPUT_DIR / f"{name}{suffix}"
                    if candidate.exists():
                        bc_cover = candidate
                        break
                if bc_cover:
                    break
            if not bc_wav:
                bc_wav = mp3_file if mp3_file.exists() else None

            if bc_wav:
                try:
                    log.info("=" * 60)
                    log.info("Uploading to Bandcamp...")
                    bandcamp_url = upload_to_bandcamp(bc_wav, concept, bc_cover)
                    result["bandcamp_url"] = bandcamp_url
                    if bandcamp_url:
                        log.info(f"Bandcamp: {bandcamp_url}")
                    else:
                        log.error("Bandcamp upload returned None — run: python main.py bandcamp-login")
                        result["errors"].append("bandcamp: upload returned None (session expired)")
                except Exception as e:
                    log.error(f"Bandcamp upload failed: {e}")
                    result["errors"].append(f"bandcamp: {e}")
            else:
                log.warning("No audio file found for Bandcamp — skipping")
                result["errors"].append("bandcamp: no audio file found")
    else:
        log.info(f"Skipping Bandcamp (--only {only})")

    # Upload to SoundCloud
    if only in (None, "soundcloud"):
        # Reuse the same WAV + cover art files
        name_variants = [track_name, track_name.replace(" ", "_")]
        sc_wav = None
        for name in name_variants:
            candidate = OUTPUT_DIR / f"{name}.wav"
            if candidate.exists():
                sc_wav = candidate
                break
        sc_cover = None
        for name in name_variants:
            for suffix in ["_cover.jpg", "_cover.png"]:
                candidate = OUTPUT_DIR / f"{name}{suffix}"
                if candidate.exists():
                    sc_cover = candidate
                    break
            if sc_cover:
                break

        if not sc_wav:
            # Fall back to MP3 if no WAV
            sc_wav = mp3_file if mp3_file.exists() else None

        if sc_wav:
            try:
                log.info("=" * 60)
                log.info("Uploading to SoundCloud...")
                soundcloud_url = upload_to_soundcloud(sc_wav, concept, sc_cover)
                result["soundcloud_url"] = soundcloud_url
                if soundcloud_url:
                    log.info(f"SoundCloud: {soundcloud_url}")
                else:
                    log.error("SoundCloud upload returned None — run: python main.py soundcloud-login")
                    result["errors"].append("soundcloud: upload returned None (session expired)")
            except Exception as e:
                log.error(f"SoundCloud upload failed: {e}")
                result["errors"].append(f"soundcloud: {e}")
        else:
            log.warning(f"No audio file found for SoundCloud (tried WAV + MP3) — skipping")
            result["errors"].append("soundcloud: no audio file found")
    else:
        log.info(f"Skipping SoundCloud (--only {only})")

    # Summary
    log.info("=" * 60)
    if result["errors"]:
        log.warning(f"Completed with errors: {result['errors']}")
    else:
        log.info("REUPLOAD DONE! Track uploaded successfully!")
    log.info(f"Track: {track_name}")
    log.info(f"YouTube: {result.get('youtube_url', 'N/A')}")
    log.info(f"TikTok: {result.get('tiktok_url', 'N/A')}")
    log.info(f"TuneCore: {result.get('tunecore_url', 'N/A')}")
    log.info(f"Bandcamp: {result.get('bandcamp_url', 'N/A')}")
    log.info(f"SoundCloud: {result.get('soundcloud_url', 'N/A')}")

    return result


def _format_duration(seconds: float) -> str:
    """Format seconds into mm:ss string."""
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins}:{secs:02d}"


def prepare_track_assets(mp3_path: Path, concept) -> dict:
    """Run steps 1-4 of the pipeline: probe duration → concept → thumbnail → video.

    Does NOT upload anywhere. Used by split-upload mode where the second track
    is queued for later. Returns a dict with keys: duration, duration_sec,
    thumbnail_path, cover_path, video_path, wav_path, mp3_path, concept.

    Raises on any step failure — caller decides what to do.
    """
    ensure_path()
    wav_path = mp3_path.with_suffix(".wav")
    audio_path = wav_path if wav_path.exists() else mp3_path

    log.info("=" * 60)
    log.info(f"PREP STEP 1: Reading audio: {audio_path.name}")
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", str(audio_path)],
        capture_output=True, text=True,
    )
    duration_sec = float(json.loads(probe.stdout)["format"]["duration"])
    duration_str = _format_duration(duration_sec)
    log.info(f"Duration: {duration_str}")

    # Inject duration into YouTube title/description (same logic as process_single_track)
    duration_mins = int(duration_sec) // 60
    if "\U0001f525" in concept.youtube_title:
        concept.youtube_title = concept.youtube_title.replace(
            "\U0001f525", f"\U0001f525 {duration_mins} Minutes of", 1
        )
    concept.youtube_title = concept.youtube_title[:100]
    concept.youtube_description = concept.youtube_description.replace(
        "{duration}", str(duration_mins)
    )
    concept.youtube_description += f"\n\nDuration: {duration_str}"

    log.info("=" * 60)
    log.info("PREP STEP 2: Generating thumbnail + cover art...")
    thumbnail_path, cover_path = generate_thumbnail_and_cover(
        concept.thumbnail_prompt, concept.track_name, DEFAULT_ARTIST
    )
    log.info(f"Thumbnail: {thumbnail_path} | Cover: {cover_path}")

    log.info("=" * 60)
    log.info(f"PREP STEP 3: Creating video with {audio_path.suffix} audio...")
    video_path = create_video(audio_path, thumbnail_path, concept)
    log.info(f"Video: {video_path}")

    return {
        "duration": duration_str,
        "duration_sec": duration_sec,
        "mp3_path": mp3_path,
        "wav_path": wav_path if wav_path.exists() else None,
        "thumbnail_path": Path(thumbnail_path),
        "cover_path": Path(cover_path) if cover_path else None,
        "video_path": Path(video_path),
        "concept": concept,
    }


def upload_prepared_track(prepared: dict) -> dict:
    """Upload an already-prepared track (video + thumbnail + cover) to all
    configured platforms. Mirrors steps 5-9 of `process_single_track`.

    `prepared` is the dict returned by `prepare_track_assets` (or loaded from
    a pending-upload sidecar).
    """
    concept = prepared["concept"]
    video = prepared["video_path"]
    thumbnail_path = prepared["thumbnail_path"]
    cover_path = prepared.get("cover_path")
    wav_path = prepared.get("wav_path")
    mp3_path = prepared.get("mp3_path")
    extra_playlists = prepared.get("extra_playlists")
    profile_data = prepared.get("profile_data")

    result = {
        "file": str(mp3_path) if mp3_path else None,
        "concept": concept.track_name,
        "duration": prepared.get("duration"),
        "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
        "video_path": str(video) if video else None,
        "youtube_url": None,
        "tiktok_url": None,
        "tunecore_url": None,
        "bandcamp_url": None,
        "soundcloud_url": None,
        "errors": [],
    }

    # YouTube
    try:
        log.info("=" * 60)
        log.info("Uploading to YouTube...")
        youtube_url = upload_to_youtube(video, thumbnail_path, concept,
                                        extra_playlists=extra_playlists,
                                        profile_data=profile_data)
        result["youtube_url"] = youtube_url
        if youtube_url:
            log.info(f"YouTube URL: {youtube_url}")
        else:
            result["errors"].append("youtube: upload returned None")
    except Exception as e:
        log.error(f"YouTube upload failed: {e}")
        result["errors"].append(f"youtube: {e}")

    # TikTok
    if SKIP_TIKTOK:
        log.info("TikTok SKIPPED (SKIP_TIKTOK=true)")
    else:
        try:
            log.info("=" * 60)
            log.info("Uploading to TikTok...")
            tiktok_url = upload_to_tiktok(video, concept)
            result["tiktok_url"] = tiktok_url
            if tiktok_url:
                log.info(f"TikTok: {tiktok_url}")
            else:
                result["errors"].append("tiktok: upload returned None")
        except Exception as e:
            log.error(f"TikTok upload failed: {e}")
            result["errors"].append(f"tiktok: {e}")

    # Trim silence from WAV before TuneCore/SoundCloud upload
    _tc_ready = False
    if wav_path and wav_path.exists():
        from modules.audio_merger import trim_silence, is_tunecore_ready
        trim_silence(wav_path)
        _tc_ready = is_tunecore_ready(wav_path)

    # TuneCore
    if SKIP_TUNECORE:
        log.info("TuneCore SKIPPED")
    elif not _tc_ready:
        log.warning("TuneCore SKIPPED — audio does not meet requirements (silence/duration)")
    elif cover_path and wav_path and wav_path.exists():
        try:
            log.info("=" * 60)
            log.info("Uploading to TuneCore...")
            tc_url = upload_to_tunecore(wav_path, cover_path, concept)
            result["tunecore_url"] = tc_url
            if tc_url:
                log.info(f"TuneCore: {tc_url}")
            else:
                result["errors"].append("tunecore: upload returned None")
        except Exception as e:
            log.error(f"TuneCore upload failed: {e}")
            result["errors"].append(f"tunecore: {e}")
    else:
        log.warning("TuneCore skipped — WAV or cover art missing")

    # Bandcamp (right after TuneCore)
    if SKIP_BANDCAMP:
        log.info("Bandcamp SKIPPED")
    elif wav_path and wav_path.exists():
        try:
            log.info("=" * 60)
            log.info("Uploading to Bandcamp...")
            bc_cover = cover_path if cover_path else None
            bc_url = upload_to_bandcamp(wav_path, concept, bc_cover)
            result["bandcamp_url"] = bc_url
            if bc_url:
                log.info(f"Bandcamp: {bc_url}")
            else:
                result["errors"].append("bandcamp: upload returned None")
        except Exception as e:
            log.error(f"Bandcamp upload failed: {e}")
            result["errors"].append(f"bandcamp: {e}")
    else:
        log.warning("Bandcamp skipped — WAV missing")

    # SoundCloud
    if SKIP_SOUNDCLOUD:
        log.info("SoundCloud SKIPPED")
    elif wav_path and wav_path.exists():
        try:
            log.info("=" * 60)
            log.info("Uploading to SoundCloud...")
            sc_thumb = cover_path if cover_path else None
            sc_url = upload_to_soundcloud(wav_path, concept, sc_thumb)
            result["soundcloud_url"] = sc_url
            if sc_url:
                log.info(f"SoundCloud: {sc_url}")
            else:
                result["errors"].append("soundcloud: upload returned None")
        except Exception as e:
            log.error(f"SoundCloud upload failed: {e}")
            result["errors"].append(f"soundcloud: {e}")
    else:
        log.warning("SoundCloud skipped — WAV missing")

    log.info("=" * 60)
    if result["errors"]:
        log.warning(f"Completed with errors: {result['errors']}")
    else:
        log.info("Upload DONE!")
    return result


def flush_pending_uploads() -> list[dict]:
    """Upload every track currently in the pending-upload queue.

    Used by the late-day scheduler slot (e.g. 18:00) to finish uploading the
    second song from each Suno split-generation. Successful entries are
    removed from the queue; failed entries stay for the next run.
    """
    from modules import pending_uploads

    pending = pending_uploads.list_pending()
    if not pending:
        log.info("No pending uploads to flush.")
        return []

    log.info(f"Flushing {len(pending)} pending upload(s)...")
    results = []
    for sidecar in pending:
        log.info("#" * 60)
        log.info(f"Flushing: {sidecar.name}")
        try:
            concept, payload = pending_uploads.load(sidecar)
            video = Path(payload["video_path"])
            thumb = Path(payload["thumbnail_path"])
            cover = Path(payload["cover_path"]) if payload.get("cover_path") else None
            wav = Path(payload["wav_path"]) if payload.get("wav_path") else None
            mp3 = Path(payload["mp3_path"]) if payload.get("mp3_path") else None

            if not video.exists():
                log.error(f"Video missing for {sidecar.name}: {video}")
                results.append({"sidecar": sidecar.name, "errors": [f"video missing: {video}"]})
                continue

            prepared = {
                "concept": concept,
                "video_path": video,
                "thumbnail_path": thumb,
                "cover_path": cover,
                "wav_path": wav,
                "mp3_path": mp3,
                "duration": payload.get("duration"),
            }
            result = upload_prepared_track(prepared)
            result["sidecar"] = sidecar.name
            results.append(result)

            # Consider it done if YouTube (the primary target) succeeded.
            # TuneCore/SoundCloud failures are often session issues we can
            # retry manually — don't block the queue on them.
            if result.get("youtube_url"):
                pending_uploads.mark_done(sidecar)
            else:
                log.warning(f"Keeping {sidecar.name} in queue — YouTube upload did not succeed")
        except Exception as e:
            log.error(f"Failed to flush {sidecar.name}: {e}")
            results.append({"sidecar": sidecar.name, "errors": [str(e)]})
    return results


def process_single_track(mp3_path: Path, concept=None,
                         extra_playlists: list[str] | None = None,
                         profile_data: dict | None = None) -> dict:
    """Process one compiled MP3 file: concept → thumbnail → video → upload.

    Args:
        mp3_path: Path to the MP3 file.
        concept: Optional pre-generated MusicConcept. If None, generates one.
        extra_playlists: Additional YouTube playlist names (from profile).
        profile_data: Playlist profile dict for enriching YouTube metadata.
    """
    ensure_path()
    result = {
        "file": str(mp3_path),
        "concept": None,
        "duration": None,
        "thumbnail_path": None,
        "video_path": None,
        "youtube_url": None,
        "tiktok_url": None,
        "tunecore_url": None,
        "bandcamp_url": None,
        "soundcloud_url": None,
        "errors": [],
    }

    # Determine WAV path (audio_merger already creates it alongside MP3)
    wav_path = mp3_path.with_suffix(".wav")

    # Step 1: Detect audio duration (prefer WAV, fall back to MP3)
    audio_path = wav_path if wav_path.exists() else mp3_path
    try:
        log.info("=" * 60)
        log.info(f"STEP 1: Reading audio file: {audio_path.name}")
        probe = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", str(audio_path),
            ],
            capture_output=True, text=True,
        )
        duration_sec = float(json.loads(probe.stdout)["format"]["duration"])
        duration_str = _format_duration(duration_sec)
        result["duration"] = duration_str
        log.info(f"Duration: {duration_str} ({duration_sec:.1f} seconds)")
    except Exception as e:
        log.error(f"Failed to read audio: {e}")
        result["errors"].append(f"audio: {e}")
        return result

    # Step 2: Generate concept (or use pre-generated one)
    try:
        if concept is None:
            log.info("=" * 60)
            log.info("STEP 2: Generating music concept...")
            concept = generate_concept()
        result["concept"] = concept.track_name
        log.info(f"Track name: {concept.track_name}")
        log.info(f"Mood: {concept.mood}")
        log.info(f"YouTube title: {concept.youtube_title}")

        # Inject duration into YouTube title
        duration_mins = int(duration_sec) // 60
        if "\U0001f525" in concept.youtube_title:
            concept.youtube_title = concept.youtube_title.replace(
                "\U0001f525", f"\U0001f525 {duration_mins} Minutes of", 1
            )
        concept.youtube_title = concept.youtube_title[:100]

        # Replace {duration} placeholder in description
        concept.youtube_description = concept.youtube_description.replace(
            "{duration}", str(duration_mins)
        )
        concept.youtube_description += f"\n\nDuration: {duration_str}"
    except Exception as e:
        log.error(f"Concept generation failed: {e}")
        result["errors"].append(f"concept: {e}")
        return result

    # Step 3: Generate thumbnail + cover art from ONE DALL-E call (saves API cost)
    cover_path = None
    try:
        log.info("=" * 60)
        log.info("STEP 3: Generating thumbnail + TuneCore cover art (single DALL-E call)...")
        artist_name = DEFAULT_ARTIST
        thumbnail_path, cover_path = generate_thumbnail_and_cover(
            concept.thumbnail_prompt, concept.track_name, artist_name
        )
        result["thumbnail_path"] = str(thumbnail_path)
        result["cover_path"] = str(cover_path)
        log.info(f"Thumbnail: {thumbnail_path}")
        log.info(f"Cover art: {cover_path}")
    except Exception as e:
        log.error(f"Thumbnail generation failed: {e}")
        result["errors"].append(f"thumbnail: {e}")
        return result

    # Step 4: Create video (1920x1080 — works for YouTube & TikTok)
    # Use WAV for better audio quality (ffmpeg re-encodes to AAC anyway)
    try:
        log.info("=" * 60)
        log.info(f"STEP 4: Creating video (1920x1080) with {audio_path.suffix} audio...")
        video = create_video(audio_path, thumbnail_path, concept)
        result["video_path"] = str(video)
        log.info(f"Video: {video}")
    except Exception as e:
        log.error(f"Video creation failed: {e}")
        result["errors"].append(f"video: {e}")
        return result

    # Step 4b: Generate chapters from audio energy analysis
    chapters = generate_chapters(audio_path)
    if chapters:
        concept.youtube_description = f"{chapters}\n\n{concept.youtube_description}"
        log.info(f"Added {chapters.count(chr(10)) + 1} chapters to description")

    # Step 5: Upload to YouTube
    try:
        log.info("=" * 60)
        log.info("STEP 5: Uploading to YouTube...")
        youtube_url = upload_to_youtube(video, thumbnail_path, concept,
                                        extra_playlists=extra_playlists,
                                        profile_data=profile_data)
        result["youtube_url"] = youtube_url
        if youtube_url:
            log.info(f"YouTube URL: {youtube_url}")
        else:
            log.error("YouTube upload returned None — check client_secrets.json and OAuth token")
            result["errors"].append("youtube: upload returned None (check client_secrets.json / OAuth)")
    except Exception as e:
        log.error(f"YouTube upload failed: {e}")
        result["errors"].append(f"youtube: {e}")

    # Step 5b: Post engagement comment on long video
    if youtube_url and profile_data:
        import random
        video_comments = profile_data.get("video_comments", [])
        if video_comments:
            video_id = youtube_url.split("/")[-1]
            comment_text = random.choice(video_comments)
            post_comment(video_id, comment_text)

    # Step 5c: Create and upload YouTube Short (45s vertical clip from loudest segment)
    try:
        log.info("=" * 60)
        log.info("STEP 5c: Creating YouTube Short...")
        short_video = create_short_video(audio_path, thumbnail_path, concept)
        short_title = f"{concept.track_name} 🔥 #afrohouse #shorts"[:100]
        short_desc = (
            f"Full track ➡️ {result.get('youtube_url', 'check channel')}\n\n"
            f"{concept.description}\n\n"
            f"#shorts #afrohouse #deephouse #{concept.genre.lower().replace(' ', '')}"
        )
        from modules.youtube_uploader import upload_short_to_youtube
        short_url = upload_short_to_youtube(short_video, short_title, short_desc, concept)
        result["short_url"] = short_url
        if short_url:
            log.info(f"YouTube Short URL: {short_url}")

            # Post engagement comment on Short
            if profile_data:
                short_comments = profile_data.get("short_comments", [])
                if short_comments:
                    short_vid_id = short_url.split("/")[-1]
                    post_comment(short_vid_id, random.choice(short_comments))
    except Exception as e:
        log.error(f"YouTube Short failed: {e}")
        result["errors"].append(f"youtube_short: {e}")

    # Step 6: Upload to TikTok
    if SKIP_TIKTOK:
        log.info("=" * 60)
        log.info("STEP 6: TikTok SKIPPED (SKIP_TIKTOK=true)")
    else:
        try:
            log.info("=" * 60)
            log.info("STEP 6: Uploading to TikTok...")
            tiktok_url = upload_to_tiktok(video, concept)
            result["tiktok_url"] = tiktok_url
            if tiktok_url:
                log.info(f"TikTok: {tiktok_url}")
            else:
                log.error("TikTok upload returned None — check cookies/login above")
                result["errors"].append("tiktok: upload returned None (cookies expired or login redirect)")
        except Exception as e:
            log.error(f"TikTok upload failed: {e}")
            result["errors"].append(f"tiktok: {e}")

    # Step 7: Cover art already generated in Step 3 (combined DALL-E call)
    if not cover_path:
        try:
            log.info("=" * 60)
            log.info("STEP 7: Cover art missing from Step 3 — generating separately...")
            artist_name = DEFAULT_ARTIST
            cover_path = generate_cover_art(
                concept.thumbnail_prompt, concept.track_name, artist_name
            )
            result["cover_path"] = str(cover_path)
            log.info(f"Cover art: {cover_path}")
        except Exception as e:
            log.error(f"Cover art generation failed: {e}")
            result["errors"].append(f"cover_art: {e}")
    else:
        log.info("=" * 60)
        log.info("STEP 7: Cover art already generated in Step 3 — skipping")

    # Step 7½: Trim silence from WAV before TuneCore/SoundCloud
    # TuneCore rejects tracks with >5s of silence anywhere in the audio.
    if wav_path.exists():
        from modules.audio_merger import trim_silence, is_tunecore_ready
        log.info("=" * 60)
        log.info("STEP 7½: Trimming silence from WAV for TuneCore/SoundCloud...")
        trim_silence(wav_path)
        _tc_ready = is_tunecore_ready(wav_path)
    else:
        _tc_ready = False

    # Step 8: Upload to TuneCore
    if SKIP_TUNECORE:
        log.info("=" * 60)
        log.info("STEP 8: TuneCore SKIPPED (SKIP_TUNECORE=true)")
    elif not _tc_ready:
        log.warning("STEP 8: TuneCore SKIPPED — audio does not meet requirements (silence/duration)")
        result["errors"].append("tunecore: audio failed silence/duration check")
    elif cover_path and wav_path.exists():
        try:
            log.info("=" * 60)
            log.info("STEP 8: Uploading to TuneCore...")
            tunecore_url = upload_to_tunecore(wav_path, cover_path, concept)
            result["tunecore_url"] = tunecore_url
            if tunecore_url:
                log.info(f"TuneCore: {tunecore_url}")
            else:
                log.error("TuneCore upload returned None — run: python main.py tunecore-login")
                result["errors"].append("tunecore: upload returned None (session expired)")
        except Exception as e:
            log.error(f"TuneCore upload failed: {e}")
            result["errors"].append(f"tunecore: {e}")
    else:
        if not wav_path.exists():
            log.warning(f"WAV file not found ({wav_path}) — skipping TuneCore")
            result["errors"].append(f"tunecore: WAV not found at {wav_path}")
        if not cover_path:
            log.warning("Cover art not generated — skipping TuneCore")

    # Step 9: Upload to Bandcamp (right after TuneCore)
    if SKIP_BANDCAMP:
        log.info("=" * 60)
        log.info("STEP 9: Bandcamp SKIPPED (SKIP_BANDCAMP=true)")
    elif wav_path.exists():
        try:
            log.info("=" * 60)
            log.info("STEP 9: Uploading to Bandcamp...")
            bc_cover = Path(cover_path) if cover_path else None
            bandcamp_url = upload_to_bandcamp(wav_path, concept, bc_cover)
            result["bandcamp_url"] = bandcamp_url
            if bandcamp_url:
                log.info(f"Bandcamp: {bandcamp_url}")
            else:
                log.error("Bandcamp upload returned None — run: python main.py bandcamp-login")
                result["errors"].append("bandcamp: upload returned None (session expired)")
        except Exception as e:
            log.error(f"Bandcamp upload failed: {e}")
            result["errors"].append(f"bandcamp: {e}")
    else:
        log.warning(f"WAV file not found ({wav_path}) — skipping Bandcamp")
        result["errors"].append(f"bandcamp: WAV not found at {wav_path}")

    # Step 10: Upload to SoundCloud (uses same WAV + cover art as TuneCore)
    if SKIP_SOUNDCLOUD:
        log.info("=" * 60)
        log.info("STEP 10: SoundCloud SKIPPED (SKIP_SOUNDCLOUD=true)")
    elif wav_path.exists():
        try:
            log.info("=" * 60)
            log.info("STEP 10: Uploading to SoundCloud...")
            # Use cover art as thumbnail (1600x1600 works well on SoundCloud)
            sc_thumbnail = Path(cover_path) if cover_path else None
            soundcloud_url = upload_to_soundcloud(wav_path, concept, sc_thumbnail)
            result["soundcloud_url"] = soundcloud_url
            if soundcloud_url:
                log.info(f"SoundCloud: {soundcloud_url}")
            else:
                log.error("SoundCloud upload returned None — run: python main.py soundcloud-login")
                result["errors"].append("soundcloud: upload returned None (session expired)")
        except Exception as e:
            log.error(f"SoundCloud upload failed: {e}")
            result["errors"].append(f"soundcloud: {e}")
    else:
        log.warning(f"WAV file not found ({wav_path}) — skipping SoundCloud")
        result["errors"].append(f"soundcloud: WAV not found at {wav_path}")

    # Summary
    log.info("=" * 60)
    if result["errors"]:
        log.warning(f"Completed with errors: {result['errors']}")
    else:
        log.info("DONE! Track uploaded successfully!")
    log.info(f"Track: {result['concept']}")
    log.info(f"Duration: {result['duration']}")
    log.info(f"YouTube: {result.get('youtube_url', 'N/A')}")
    log.info(f"TikTok: {result.get('tiktok_url', 'N/A')}")
    log.info(f"TuneCore: {result.get('tunecore_url', 'N/A')}")
    log.info(f"Bandcamp: {result.get('bandcamp_url', 'N/A')}")
    log.info(f"SoundCloud: {result.get('soundcloud_url', 'N/A')}")

    return result
