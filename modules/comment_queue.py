"""Persistent queue for YouTube comments that couldn't be posted yet.

Root cause this solves: uploads are scheduled premieres (private for the first
~30 min), and YouTube rejects comments on private videos. The engagement
comment used to be attempted only right after upload — every attempt hit the
still-private video and silently failed, so long videos ended up with no
pinned tracklist comment at all.

Failed comments are queued here and flushed later (at the start of the next
pipeline run and by the `engage` CLI command), once the video is public.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from config import OUTPUT_DIR

log = logging.getLogger("music_pipeline")

QUEUE_FILE = Path(OUTPUT_DIR) / "pending_comments.json"
MAX_ATTEMPTS = 8          # give up after this many flush attempts
MAX_AGE_HOURS = 72        # or when the entry is older than this


def _load() -> list:
    if not QUEUE_FILE.exists():
        return []
    try:
        data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        return data.get("pending", []) if isinstance(data, dict) else []
    except (OSError, json.JSONDecodeError):
        log.warning("comment_queue: queue unreadable — starting empty")
        return []


def _save(pending: list) -> None:
    tmp = QUEUE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"pending": pending}, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(QUEUE_FILE)


def queue_comment(video_id: str, text: str) -> None:
    """Remember a comment to retry once the video is public."""
    pending = _load()
    pending.append({
        "video_id": video_id,
        "text": text,
        "queued_at": datetime.now().isoformat(timespec="seconds"),
        "attempts": 0,
    })
    _save(pending)
    log.info(f"comment_queue: queued comment for {video_id} "
             f"({len(pending)} pending)")


def flush_pending_comments() -> int:
    """Try to post every queued comment. Returns how many were posted."""
    pending = _load()
    if not pending:
        return 0

    from modules.youtube_uploader import post_comment

    posted = 0
    keep = []
    now = datetime.now()
    for entry in pending:
        try:
            age = now - datetime.fromisoformat(entry["queued_at"])
        except (KeyError, ValueError):
            age = timedelta(0)
        if entry.get("attempts", 0) >= MAX_ATTEMPTS or age > timedelta(hours=MAX_AGE_HOURS):
            log.warning(f"comment_queue: giving up on {entry.get('video_id')} "
                        f"(attempts={entry.get('attempts')}, age={age})")
            continue

        cid = post_comment(entry["video_id"], entry["text"])
        if cid:
            posted += 1
            log.info(f"comment_queue: posted queued comment on {entry['video_id']}")
        else:
            entry["attempts"] = entry.get("attempts", 0) + 1
            keep.append(entry)

    _save(keep)
    if posted or keep:
        log.info(f"comment_queue: flushed {posted}, {len(keep)} still pending")
    return posted
