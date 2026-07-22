"""Persistent upload guard — enforces the recovery-pipeline volume cap.

Phase 1 of RECOVERY PIPELINE v3. Two protections, both backed by a JSON file
on disk so they survive a process restart (a crash + relaunch must NOT trigger
retroactive catch-up uploads):

  1. Weekly hard cap  — at most MAX_UPLOADS_PER_WEEK uploads per rolling 7 days.
  2. Anti-duplication — at least MIN_HOURS_BETWEEN_UPLOADS between uploads.

The guard is deliberately independent of the scheduler: `can_upload()` is
called before any upload attempt, so even a manual run (without --force) is
capped. `record_upload()` is called only after a confirmed successful upload.

All datetimes are timezone-naive local time (datetime.now()); the guard only
ever compares deltas, never absolute wall-clock across zones.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from config import (
    UPLOAD_HISTORY_FILE,
    MAX_UPLOADS_PER_WEEK,
    MIN_HOURS_BETWEEN_UPLOADS,
)

log = logging.getLogger("music_pipeline")


def _load() -> list:
    """Return the list of recorded uploads (newest-last). Never raises."""
    path = Path(UPLOAD_HISTORY_FILE)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"upload_guard: history file unreadable ({e}) — treating as empty")
        return []
    uploads = data.get("uploads", []) if isinstance(data, dict) else []
    return uploads if isinstance(uploads, list) else []


def _save(uploads: list) -> None:
    path = Path(UPLOAD_HISTORY_FILE)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {"uploads": uploads[-200:]}  # keep the last 200 records
    # Write to a temp file then atomically replace — a crash mid-write can
    # never corrupt the real history file.
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _parsed_dates(uploads: list) -> list:
    out = []
    for u in uploads:
        try:
            out.append(datetime.fromisoformat(u["ts"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _same_iso_week(a: datetime, b: datetime) -> bool:
    """True if two datetimes fall in the same ISO calendar week (Mon–Sun)."""
    ya, wa, _ = a.isocalendar()
    yb, wb, _ = b.isocalendar()
    return (ya, wa) == (yb, wb)


def recent_uploads(now: datetime = None) -> list:
    """Uploads recorded in the current ISO calendar week (Mon–Sun)."""
    now = now or datetime.now()
    return [d for d in _parsed_dates(_load()) if _same_iso_week(d, now)]


def can_upload(now: datetime = None) -> tuple:
    """Return (allowed: bool, reason: str).

    Blocks when the last upload was too recent OR this ISO calendar week's cap
    is already reached. A calendar week (not a rolling 7-day window) is used on
    purpose: a fixed weekday schedule (e.g. Tue/Thu/Sat) puts all three slots in
    the same week and resets cleanly, whereas a rolling window would wrongly
    block the slot that lands exactly 7 days after the previous week's first.
    """
    now = now or datetime.now()
    dates = _parsed_dates(_load())

    if dates:
        last = max(dates)
        gap_h = (now - last).total_seconds() / 3600.0
        if gap_h < MIN_HOURS_BETWEEN_UPLOADS:
            return False, (
                f"last upload was {gap_h:.1f}h ago "
                f"(minimum gap {MIN_HOURS_BETWEEN_UPLOADS}h) — skipping"
            )

    week = [d for d in dates if _same_iso_week(d, now)]
    if len(week) >= MAX_UPLOADS_PER_WEEK:
        return False, (
            f"{len(week)} upload(s) already this calendar week "
            f"(cap {MAX_UPLOADS_PER_WEEK}) — skipping"
        )

    return True, f"ok — {len(week)}/{MAX_UPLOADS_PER_WEEK} used this week"


def record_upload(title: str = None, video_id: str = None, now: datetime = None) -> None:
    """Append a successful upload to the persistent history."""
    now = now or datetime.now()
    uploads = _load()
    uploads.append(
        {
            "ts": now.isoformat(timespec="seconds"),
            "title": title,
            "video_id": video_id,
        }
    )
    _save(uploads)
    log.info(
        f"upload_guard: recorded '{title or '?'}' at "
        f"{now.isoformat(timespec='seconds')} "
        f"({len(recent_uploads(now=now))}/{MAX_UPLOADS_PER_WEEK} this week)"
    )
