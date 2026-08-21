import json
import subprocess
from pathlib import Path

from utils.logger import log
from utils.auto_setup import ensure_path
from modules.concept_generator import generate_concept
from modules.thumbnail_generator import generate_thumbnail, generate_cover_art, generate_thumbnail_and_cover
from modules.video_creator import create_video, create_short_video, create_multiple_shorts, generate_chapters
from modules.youtube_uploader import upload_to_youtube, post_comment
from modules.tiktok_uploader import upload_to_tiktok
from modules.tunecore_uploader import upload_to_tunecore
from modules.distrokid_uploader import upload_to_distrokid
from modules.soundcloud_uploader import upload_to_soundcloud
from modules.bandcamp_uploader import upload_to_bandcamp
from config import SKIP_TUNECORE, SKIP_SOUNDCLOUD, SKIP_TIKTOK, SKIP_BANDCAMP, SKIP_SHORTS, SKIP_DISTROKID

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

    # "latest" is a sentinel meaning "the most recently created track". Resolve
    # it to the real track name from the newest audio file so the release isn't
    # literally titled "latest" (and the cover doesn't say "LATEST").
    if track_name.strip().lower() == "latest":
        audio = sorted(
            list(OUTPUT_DIR.glob("*.wav")) + list(OUTPUT_DIR.glob("*.mp3")),
            key=lambda f: f.stat().st_mtime, reverse=True,
        )
        if audio:
            real = audio[0].stem
            for suffix in ("_master", "_video", "_short", "_tiktok"):
                if real.endswith(suffix):
                    real = real[: -len(suffix)]
            log.info(f"Resolved 'latest' → real track name: {real}")
            track_name = real
        else:
            log.warning("No audio files found to resolve 'latest'")

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

    # Audio-only distributors (TuneCore, DistroKid, Bandcamp, SoundCloud) don't
    # need a video file — only YouTube/TikTok do.
    _audio_only = {"tunecore", "distrokid", "bandcamp", "soundcloud"}
    if not video and only not in _audio_only:
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
        if "minutes" not in concept.youtube_title.lower() and duration_mins >= 5:
            concept.youtube_title = f"{concept.youtube_title} [{duration_mins} Min]"
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
                # Record in the persistent guard so the weekly cap / 24h gap
                # (RECOVERY PIPELINE v3, Phase 1) survive a process restart.
                try:
                    from modules.upload_guard import record_upload
                    _vid = youtube_url.rstrip("/").split("/")[-1].split("=")[-1]
                    record_upload(title=getattr(concept, "youtube_title", None),
                                  video_id=_vid or None)
                except Exception as e:
                    log.warning(f"upload_guard: could not record upload: {e}")
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
    if only in (None, "tunecore", "youtube", "tiktok") and not SKIP_TUNECORE:
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
    elif SKIP_TUNECORE:
        log.info("Skipping TuneCore (SKIP_TUNECORE=true)")
    else:
        log.info(f"Skipping TuneCore (--only {only})")

    # Upload to DistroKid (active distributor for AI music)
    if only in (None, "distrokid") and not SKIP_DISTROKID:
        name_variants = [track_name, track_name.replace(" ", "_")]
        dk_wav = None
        for name in name_variants:
            candidate = OUTPUT_DIR / f"{name}.wav"
            if candidate.exists():
                dk_wav = candidate
                break
        # Fallback: most recently modified WAV in output/ (= the last track made)
        if not dk_wav:
            all_wavs = sorted(OUTPUT_DIR.glob("*.wav"), key=lambda f: f.stat().st_mtime, reverse=True)
            if all_wavs:
                dk_wav = all_wavs[0]
                log.info(f"WAV not found by name — using latest: {dk_wav}")

        dk_cover = None
        for name in name_variants:
            for suffix in ["_cover.jpg", "_cover.png"]:
                candidate = OUTPUT_DIR / f"{name}{suffix}"
                if candidate.exists():
                    dk_cover = candidate
                    break
            if dk_cover:
                break
        if not dk_cover:
            try:
                log.info("Generating cover art for DistroKid...")
                dk_cover = generate_cover_art(
                    concept.thumbnail_prompt, concept.track_name, DEFAULT_ARTIST
                )
            except Exception as e:
                log.error(f"Cover art generation failed: {e}")

        if dk_wav and dk_cover:
            try:
                log.info("=" * 60)
                log.info("Uploading to DistroKid...")
                distrokid_url = upload_to_distrokid(dk_wav, Path(dk_cover), concept)
                result["distrokid_url"] = distrokid_url
                if distrokid_url:
                    log.info(f"DistroKid: {distrokid_url}")
                else:
                    log.error("DistroKid upload returned None — run: python main.py distrokid-login")
                    result["errors"].append("distrokid: upload returned None (session expired)")
            except Exception as e:
                log.error(f"DistroKid upload failed: {e}")
                result["errors"].append(f"distrokid: {e}")
        else:
            log.warning("No audio/cover for DistroKid — skipping")
            result["errors"].append("distrokid: no audio/cover found")
    elif SKIP_DISTROKID:
        log.info("Skipping DistroKid (SKIP_DISTROKID=true)")
    else:
        log.info(f"Skipping DistroKid (--only {only})")

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
    if "minutes" not in concept.youtube_title.lower() and duration_mins >= 5:
        concept.youtube_title = f"{concept.youtube_title} [{duration_mins} Min]"
    concept.youtube_title = concept.youtube_title[:100]
    concept.youtube_description = concept.youtube_description.replace(
        "{duration}", str(duration_mins)
    )
    concept.youtube_description += f"\n\nDuration: {duration_str}"

    log.info("=" * 60)
    log.info("PREP STEP 2: Generating thumbnail + cover art...")
    thumbnail_path, cover_path = generate_thumbnail_and_cover(
        concept.thumbnail_prompt, concept.track_name, DEFAULT_ARTIST,
        youtube_title=concept.youtube_title,
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


def _build_tracklist(segment_files: list) -> str:
    """Build a YouTube-comment-ready tracklist with cumulative timestamps.

    Reads each segment MP3's duration via mutagen and produces:
        🎵 TRACKLIST 🎵
        0:00 — Intro
        2:13 — Rising Energy
        ...
    Returns an empty string on any error so the caller can fall back to a
    plain engagement comment.
    """
    try:
        from mutagen.mp3 import MP3
    except Exception:
        log.info("mutagen not available — skipping tracklist generation")
        return ""

    segment_labels = [
        "Intro", "Rising Energy", "First Drop", "Deep Groove",
        "Building Up", "Peak Moment", "Breakdown", "Second Drop",
        "Tribal Heat", "Sunset Vibes", "Late Night", "Outro",
    ]

    lines = ["🎵 TRACKLIST 🎵"]
    cumul = 0
    for i, seg in enumerate(segment_files):
        try:
            mp3 = MP3(str(seg))
            dur = int(mp3.info.length)
        except Exception as e:
            log.warning(f"Could not read duration of {seg}: {e}")
            return ""
        m, s = divmod(cumul, 60)
        label = segment_labels[i] if i < len(segment_labels) else f"Section {i + 1}"
        lines.append(f"{m}:{s:02d} — {label}")
        cumul += dur

    lines.append("")
    lines.append("💬 Which part hit hardest? Drop the timestamp below!")
    return "\n".join(lines)


def post_community_announcement(video_url: str, track_name: str,
                                concept_description: str = "") -> bool:
    """Post a Community-tab announcement on YouTube linking to the new video.

    Uses Playwright + saved YouTube cookies. Returns True on success.
    YouTube Data API has no insert endpoint for community posts so this
    must go through Studio's web UI.
    """
    from config import OUTPUT_DIR
    try:
        from playwright.sync_api import sync_playwright
        from modules.youtube_uploader import get_browser_context, YOUTUBE_COOKIE_FILE
    except Exception as e:
        log.warning(f"Cannot post community update — Playwright/uploader missing: {e}")
        return False

    if not YOUTUBE_COOKIE_FILE.exists():
        log.info("Skipping community post — YouTube cookie file not found")
        return False

    desc = (concept_description or "").strip().replace("\n", " ")[:180]
    post_text = (
        f"🔥 New mix is LIVE 🔥\n\n"
        f"{track_name}\n"
        f"{desc}\n\n"
        f"👉 Watch the full mix: {video_url}\n"
        f"🔔 Subscribe + bell so you don't miss the next one"
    )

    log.info(f"Posting Community tab announcement for {track_name}...")
    with sync_playwright() as p:
        try:
            browser, context = get_browser_context(p, YOUTUBE_COOKIE_FILE)
            page = context.new_page()
            page.goto("https://www.youtube.com/", wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(4000)
            # Open the channel "Create" → community-post composer.
            page.goto("https://studio.youtube.com/channel/UC/community/post", wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(6000)

            if "accounts.google.com" in page.url:
                log.warning("Community post: not logged in (cookies expired)")
                browser.close()
                return False

            # Find composer textarea / contenteditable and fill it.
            filled = False
            for sel in [
                "div[contenteditable='true']",
                "ytcp-social-suggestions-textbox div[contenteditable]",
                "textarea[aria-label*='post' i]",
                "textarea",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=2000):
                        el.click()
                        el.fill(post_text)
                        filled = True
                        log.info(f"Community composer filled via selector: {sel}")
                        break
                except Exception:
                    continue

            if not filled:
                page.screenshot(path=str(OUTPUT_DIR / "debug_community_no_composer.png"))
                log.warning("Could not find community-post composer")
                browser.close()
                return False

            page.wait_for_timeout(2000)

            # Click the Post button.
            for sel in [
                "button:has-text('Post')", "tp-yt-paper-button:has-text('Post')",
                "ytcp-button:has-text('Post')", "button[aria-label*='Post' i]",
            ]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        log.info(f"Clicked community Post button via selector: {sel}")
                        page.wait_for_timeout(5000)
                        browser.close()
                        return True
                except Exception:
                    continue

            page.screenshot(path=str(OUTPUT_DIR / "debug_community_no_post_btn.png"))
            log.warning("Could not find Post button in community composer")
            browser.close()
            return False
        except Exception as e:
            log.warning(f"Community post failed: {e}")
            try:
                browser.close()
            except Exception:
                pass
            return False


def process_single_track(mp3_path: Path, concept=None,
                         extra_playlists: list[str] | None = None,
                         profile_data: dict | None = None,
                         segment_files: list[Path] | None = None) -> dict:
    """Process one compiled MP3 file: concept → thumbnail → video → upload.

    Args:
        mp3_path: Path to the MP3 file.
        concept: Optional pre-generated MusicConcept. If None, generates one.
        extra_playlists: Additional YouTube playlist names (from profile).
        profile_data: Playlist profile dict for enriching YouTube metadata.
        segment_files: Optional list of source MP3s that were merged into
            mp3_path. Used to compute per-segment timestamps for the
            tracklist comment.
    """
    ensure_path()
    # Post any comments queued by previous runs (their premieres are public by
    # now) and reply to new fan comments. Runs here so the two daily upload
    # slots cover engagement too — no separate scheduled task needed.
    # Non-fatal — never block the new upload.
    try:
        from modules.comment_queue import flush_pending_comments
        flush_pending_comments()
    except Exception as e:
        log.warning(f"comment_queue flush failed: {e}")
    try:
        from modules.youtube_uploader import reply_to_new_comments
        reply_to_new_comments(max_videos=5, max_replies_per_video=2)
    except Exception as e:
        log.warning(f"auto-reply failed: {e}")
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

        # Inject duration into YouTube title — numbers boost CTR
        duration_mins = int(duration_sec) // 60
        if "minutes" not in concept.youtube_title.lower() and duration_mins >= 5:
            concept.youtube_title = f"{concept.youtube_title} [{duration_mins} Min]"
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
            concept.thumbnail_prompt, concept.track_name, artist_name,
            youtube_title=concept.youtube_title,
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

    # Step 5b: Post engagement comment on long video — DEFERRED below.
    # YouTube needs several minutes to finish transcoding the long upload
    # before comments are accepted; posting immediately fails silently.

    # Step 5c: Create and upload YouTube Shorts (skipped when SKIP_SHORTS is set)
    try:
        if SKIP_SHORTS:
            log.info("=" * 60)
            log.info("STEP 5c: SKIPPED — YouTube Shorts disabled (SKIP_SHORTS=true)")
            result["short_urls"] = []
        else:
            shorts_count = 2
            log.info("=" * 60)
            log.info(f"STEP 5c: Creating {shorts_count} YouTube Shorts...")
            short_videos = create_multiple_shorts(audio_path, thumbnail_path, concept, count=shorts_count)
            from modules.youtube_uploader import upload_short_to_youtube

            result["short_urls"] = []
            # Slight title variation per short — avoids YouTube flagging
            # duplicate uploads from same channel within minutes.
            short_title_variants = [
                f"{concept.track_name} 🔥 #afrohouse #shorts",
                f"{concept.track_name} 💥 Afro House Drop #shorts",
                f"{concept.track_name} 🥁 Tribal Bass #afrohouse #shorts",
                f"POV: {concept.track_name} 🔥 #afrohouse #shorts",
                f"{concept.track_name} • Peak Moment 🌙 #shorts #afrohouse",
            ]
            full_url = result.get("youtube_url", "check channel")
            for i, short_video in enumerate(short_videos):
                short_title = short_title_variants[i % len(short_title_variants)][:100]
                short_desc = (
                    f"Full track ➡️ {full_url}\n\n"
                    f"{concept.description}\n\n"
                    f"#shorts #afrohouse #deephouse #{concept.genre.lower().replace(' ', '')}"
                )
                try:
                    short_url = upload_short_to_youtube(short_video, short_title, short_desc, concept)
                except Exception as up_err:
                    log.warning(f"Short {i + 1}/{len(short_videos)} upload failed: {up_err}")
                    continue
                if not short_url:
                    continue
                result["short_urls"].append(short_url)
                log.info(f"YouTube Short {i + 1}/{len(short_videos)} URL: {short_url}")

                if profile_data:
                    import random as _r
                    short_comments = profile_data.get("short_comments", [])
                    if short_comments:
                        short_vid_id = short_url.split("/")[-1]
                        post_comment(short_vid_id, _r.choice(short_comments))
    except Exception as e:
        log.error(f"YouTube Shorts failed: {e}")
        result["errors"].append(f"youtube_shorts: {e}")

    # Step 5b (deferred): Now post engagement comment on the LONG video.
    # By this point the long video has had several minutes to finish
    # processing (Short creation + upload took 2-4 min), so YouTube will
    # accept the comment instead of silently rejecting it.
    youtube_url = result.get("youtube_url")
    if youtube_url and profile_data:
        import random
        import time as _t
        video_comments = profile_data.get("video_comments", [])
        if video_comments:
            video_id = youtube_url.split("/")[-1]
            comment_text = random.choice(video_comments)
            # Prepend a tracklist with timestamps when we have segment info —
            # this drives watch time (viewers click timestamps) and is a major
            # YouTube algorithm signal.
            tracklist = _build_tracklist(segment_files) if segment_files else ""
            if tracklist:
                comment_text = f"{tracklist}\n\n{comment_text}"
            # The upload is a scheduled premiere (private for ~30 min) and
            # YouTube REJECTS comments on private videos — so immediate
            # attempts usually fail. Try twice, then queue the comment; the
            # queue is flushed on the next pipeline run / `engage` command,
            # when the video is public.
            cid = None
            for attempt in range(1, 3):
                cid = post_comment(video_id, comment_text)
                if cid:
                    break
                if attempt < 2:
                    log.info(f"Long-video comment attempt {attempt} failed; waiting 90s...")
                    _t.sleep(90)
            if cid:
                # Pin it — a pinned tracklist is the whole point (API can't
                # pin, so this drives the browser). Non-fatal.
                try:
                    from modules.youtube_uploader import pin_comment
                    pin_comment(video_id, cid)
                except Exception as e:
                    log.warning(f"Pin failed (comment stays unpinned): {e}")
            else:
                from modules.comment_queue import queue_comment
                queue_comment(video_id, comment_text)
                log.info("Comment queued — will be posted once the premiere goes public")

    # Step 5d: Post Community-tab announcement linking to the long video
    if youtube_url and concept is not None:
        try:
            post_community_announcement(
                youtube_url, concept.track_name,
                getattr(concept, "description", "") or "",
            )
        except Exception as e:
            log.warning(f"Community post failed: {e}")

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

    # Step 8b: Upload to DistroKid (the active distributor for AI music)
    if SKIP_DISTROKID:
        log.info("=" * 60)
        log.info("STEP 8b: DistroKid SKIPPED (SKIP_DISTROKID=true)")
    elif cover_path and wav_path.exists():
        try:
            log.info("=" * 60)
            log.info("STEP 8b: Uploading to DistroKid...")
            distrokid_url = upload_to_distrokid(wav_path, Path(cover_path), concept)
            result["distrokid_url"] = distrokid_url
            if distrokid_url:
                log.info(f"DistroKid: {distrokid_url}")
            else:
                log.error("DistroKid upload returned None — run: python main.py distrokid-login")
                result["errors"].append("distrokid: upload returned None (session expired)")
        except Exception as e:
            log.error(f"DistroKid upload failed: {e}")
            result["errors"].append(f"distrokid: {e}")
    else:
        if not wav_path.exists():
            log.warning(f"WAV file not found ({wav_path}) — skipping DistroKid")
        if not cover_path:
            log.warning("Cover art not generated — skipping DistroKid")

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
