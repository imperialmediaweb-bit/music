"""MP3 archive pool for hybrid generation.

After each Suno/aimusicfactory generation, individual MP3s are copied into
`archive/suno_pool/` with metadata saved in `archive/catalog.json`.
When a profile uses hybrid mode, `pick_from_archive()` selects compatible
tracks to mix with fresh generations — making longer clips without extra credits.

The archive builds up automatically: first runs are 100% fresh, and once
the pool is large enough, hybrid kicks in.
"""

from __future__ import annotations

import json
import random
import shutil
import time
from pathlib import Path

from config import OUTPUT_DIR
from utils.logger import log

ARCHIVE_DIR = OUTPUT_DIR / "archive" / "suno_pool"
CATALOG_PATH = OUTPUT_DIR / "archive" / "catalog.json"


def _ensure_dirs() -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_catalog() -> list[dict]:
    if CATALOG_PATH.exists():
        try:
            return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save_catalog(catalog: list[dict]) -> None:
    CATALOG_PATH.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _is_suno(entry: dict) -> bool:
    """Identify Suno-sourced archive entries.

    TuneCore's AI detector flags Suno output reliably; AIMusicFactory passes,
    so we exclude Suno from hybrid-mode picks. Detection rules:
      - Explicit `source` field == 'suno' (set on new entries)
      - Filename or original_name contains 'suno' (legacy bootstrap files)
      - Profile == 'seed' (these were imported by seed_from_output and were
        all Afro-house Suno generations)
    """
    if (entry.get("source") or "").lower() == "suno":
        return True
    fn = (entry.get("filename") or "").lower()
    on = (entry.get("original_name") or "").lower()
    if "suno" in fn or "suno" in on:
        return True
    if (entry.get("profile") or "").lower() == "seed":
        return True
    return False


def archive_mp3s(
    mp3_paths: list[Path],
    profile_name: str = "",
    track_name: str = "",
    tags: list[str] | None = None,
    source: str = "",
) -> int:
    """Copy MP3s into the archive pool and update catalog.

    `source` records the generator platform ("aimusicfactory" / "suno") so
    `pick_from_archive` can later exclude detectable sources.

    Returns the number of files archived.
    """
    _ensure_dirs()
    catalog = _load_catalog()
    existing_names = {e["filename"] for e in catalog}
    archived = 0

    for mp3 in mp3_paths:
        if not mp3.exists():
            continue
        dest_name = f"{int(time.time())}_{mp3.name}"
        if dest_name in existing_names:
            continue
        dest = ARCHIVE_DIR / dest_name
        shutil.copy2(mp3, dest)
        catalog.append({
            "filename": dest_name,
            "original_name": mp3.name,
            "profile": profile_name,
            "track_name": track_name,
            "tags": tags or [],
            "source": source,
            "archived_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        archived += 1

    if archived:
        _save_catalog(catalog)
        log.info(f"Archived {archived} MP3(s) to pool (total: {len(catalog)})")
    return archived


def pick_from_archive(count: int, exclude_files: list[Path] | None = None) -> list[Path]:
    """Pick random MP3s from the archive pool.

    Returns up to `count` paths. If the pool is too small, returns
    whatever is available (may be empty).
    """
    catalog = _load_catalog()
    if not catalog:
        return []

    exclude_names = {p.name for p in (exclude_files or [])}
    candidates = [
        e for e in catalog
        if e["filename"] not in exclude_names
        and (ARCHIVE_DIR / e["filename"]).exists()
        and not _is_suno(e)
    ]

    selected = random.sample(candidates, min(count, len(candidates)))
    paths = [ARCHIVE_DIR / e["filename"] for e in selected]
    log.info(f"Picked {len(paths)} MP3(s) from archive (AIMusicFactory pool: {len(candidates)})")
    return paths


def archive_size() -> int:
    """Return number of non-Suno MP3s in the archive pool (the ones eligible
    for hybrid picks). Suno entries are excluded because TuneCore's AI
    detector flags them reliably."""
    return sum(1 for e in _load_catalog() if not _is_suno(e))


def seed_from_output() -> int:
    """Import individual Suno MP3s from output/ into the archive pool.

    Only imports files with _1, _2, _3... suffix (individual Suno songs),
    not merged tracks (which have no number suffix).
    Returns count of newly archived files.
    """
    import re
    _ensure_dirs()
    catalog = _load_catalog()
    existing_originals = {e["original_name"] for e in catalog}
    archived = 0

    candidates = sorted(OUTPUT_DIR.glob("*_[0-9]*.mp3"))
    pattern = re.compile(r"^.+_\d+\.mp3$")
    candidates = [f for f in candidates if pattern.match(f.name)]

    for mp3 in candidates:
        if mp3.name in existing_originals:
            continue
        if mp3.stat().st_size < 500_000:
            continue

        dest_name = f"{int(time.time())}_{archived}_{mp3.name}"
        dest = ARCHIVE_DIR / dest_name
        shutil.copy2(mp3, dest)
        catalog.append({
            "filename": dest_name,
            "original_name": mp3.name,
            "profile": "seed",
            "track_name": mp3.stem.rsplit("_", 1)[0],
            "tags": ["afrohouse", "seed"],
            "archived_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
        archived += 1

    if archived:
        _save_catalog(catalog)
    log.info(f"Seeded {archived} MP3(s) from output/ (total pool: {len(catalog)})")
    return archived
