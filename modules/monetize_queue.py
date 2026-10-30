"""Deferred monetization queue.

Every upload goes out as a PREMIERE — private with a publishAt 30 minutes
ahead — and YouTube's monetization page has nothing to offer while a video is
still private: the automation would load it, find no controls, log "may
already be done" and move on, leaving the video public-with-ads-off. Running
the same step by hand later (`monetize --recent`) always worked, which is what
gave the cause away.

So the video id is queued here at upload time and flushed on a later run, once
the premiere has gone public. Same shape as comment_queue: atomic writes, a
cap on attempts and an age limit, and fail-open on a corrupt file so a bad
queue never takes a run down.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import OUTPUT_DIR

log = logging.getLogger("music_pipeline")

QUEUE_FILE = Path(OUTPUT_DIR) / "pending_monetization.json"
MAX_ATTEMPTS = 8          # give up after this many flush attempts
MAX_AGE_HOURS = 72        # or when the entry is older than this
MIN_AGE_MINUTES = 35      # premiere needs ~30 min to go public — wait it out


def _load() -> list:
    if not QUEUE_FILE.exists():
        return []
    try:
        data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("monetize_queue: queue unreadable — starting empty")
        return []
    return data.get("pending", []) if isinstance(data, dict) else []


def _save(pending: list) -> None:
    tmp = QUEUE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"pending": pending}, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(QUEUE_FILE)


def queue_monetization(video_id: str, title: str = "") -> None:
    """Remember to switch ads on for this video once the premiere is public."""
    pending = _load()
    if any(e.get("video_id") == video_id for e in pending):
        return
    pending.append({
        "video_id": video_id,
        "title": title,
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "attempts": 0,
    })
    _save(pending)
    log.info(f"monetize_queue: queued {video_id} ({len(pending)} pending) — "
             "ads get switched on once the premiere is public")


def flush_pending_monetization() -> int:
    """Try every queued video that is old enough to be public. Returns count done."""
    pending = _load()
    if not pending:
        return 0

    from modules.youtube_uploader import _complete_self_certification

    now = datetime.now(timezone.utc)
    still, done = [], 0

    for entry in pending:
        try:
            queued = datetime.fromisoformat(entry.get("queued_at", ""))
        except ValueError:
            queued = now

        age = now - queued
        if entry.get("attempts", 0) >= MAX_ATTEMPTS or age > timedelta(hours=MAX_AGE_HOURS):
            log.warning(f"monetize_queue: giving up on {entry.get('video_id')} "
                        f"(attempts={entry.get('attempts')}, age={age})")
            continue
        if age < timedelta(minutes=MIN_AGE_MINUTES):
            still.append(entry)  # premiere still counting down
            continue

        vid = entry.get("video_id")
        try:
            if _complete_self_certification(vid):
                log.info(f"monetize_queue: ads ON for {vid} ({entry.get('title', '')})")
                done += 1
                continue
        except Exception as e:
            log.warning(f"monetize_queue: {vid} failed: {e}")

        entry["attempts"] = entry.get("attempts", 0) + 1
        still.append(entry)

    _save(still)
    if done:
        log.info(f"monetize_queue: {done} video(s) monetized, {len(still)} still pending")
    return done
