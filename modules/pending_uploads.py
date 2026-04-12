"""Pending-upload queue for deferred YouTube uploads.

Used by Suno split-upload mode: when Suno generates 2 MP3s per run, we upload
the first immediately and queue the second as a JSON sidecar in
`output/pending_uploads/`. A later scheduler slot calls `flush_pending()`,
which uploads anything queued and removes the sidecar on success.

Each sidecar contains enough info to re-run `upload_to_youtube` and
`upload_to_tiktok` without re-generating the concept, thumbnail, or video —
those artifacts are produced at queue time and live alongside in `output/`.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from config import OUTPUT_DIR
from modules.concept_generator import MusicConcept
from utils.logger import log

PENDING_DIR = OUTPUT_DIR / "pending_uploads"


def _ensure_dir() -> None:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)


def enqueue(
    concept: MusicConcept,
    video_path: Path,
    thumbnail_path: Path,
    mp3_path: Optional[Path] = None,
    wav_path: Optional[Path] = None,
    cover_path: Optional[Path] = None,
    duration_str: Optional[str] = None,
) -> Path:
    """Serialize one ready-to-upload track to the queue.

    Returns the sidecar JSON path. All referenced media files must already
    exist on disk — the flusher will not regenerate them.
    """
    _ensure_dir()
    entry_id = f"{int(time.time())}_{_safe(concept.track_name)}"
    sidecar = PENDING_DIR / f"{entry_id}.json"
    payload = {
        "id": entry_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "concept": asdict(concept),
        "video_path": str(video_path),
        "thumbnail_path": str(thumbnail_path),
        "mp3_path": str(mp3_path) if mp3_path else None,
        "wav_path": str(wav_path) if wav_path else None,
        "cover_path": str(cover_path) if cover_path else None,
        "duration": duration_str,
    }
    sidecar.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info(f"Queued pending upload: {sidecar.name}")
    return sidecar


def list_pending() -> list[Path]:
    """Return sidecar JSON files in the queue, oldest first."""
    if not PENDING_DIR.exists():
        return []
    return sorted(PENDING_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)


def load(sidecar: Path) -> tuple[MusicConcept, dict]:
    """Load a sidecar, returning (concept, raw_payload)."""
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    concept_kwargs = dict(payload["concept"])
    concept = MusicConcept(**concept_kwargs)
    return concept, payload


def mark_done(sidecar: Path) -> None:
    """Remove a sidecar after successful upload."""
    try:
        sidecar.unlink()
        log.info(f"Pending upload done — removed: {sidecar.name}")
    except OSError as e:
        log.warning(f"Could not remove sidecar {sidecar.name}: {e}")


def _safe(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_ " else "" for c in name)
    return safe.strip().replace(" ", "_")[:50] or "track"
