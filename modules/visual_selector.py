"""Thumbnail-direction and title-template selectors with rotation rules.

RECOVERY PIPELINE v3 — Phase 3. The catalogue's most visible mass-produced
signal was one thumbnail layout (tribal mask, red/orange, same composition) and
one title formula. This module rotates:

  - Thumbnail directions: never the same direction twice in a row, and no
    direction more than twice in the last 6 uploads.
  - Title templates: not repeated within the last TITLE_HISTORY_WINDOW picks.

Both histories are persisted atomically so the rules survive process restarts.
Selectors accept an injectable RNG for deterministic tests.
"""
import json
import logging
import random
from pathlib import Path

from config import (
    THUMBNAIL_DIRECTIONS_FILE,
    THUMBNAIL_DIRECTION_HISTORY_FILE,
    TITLE_TEMPLATES_FILE,
    TITLE_HISTORY_FILE,
    TITLE_HISTORY_WINDOW,
)

log = logging.getLogger("music_pipeline")

# Direction rule constants (per the brief).
_DIR_WINDOW = 6         # look back this many uploads
_DIR_MAX_IN_WINDOW = 2  # a direction may appear at most twice in that window


def _read_json(path, key):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"visual_selector: cannot read {path}: {e}")
    items = data.get(key, [])
    if not items:
        raise RuntimeError(f"visual_selector: {path} has no '{key}'")
    return items


def _load_history(path):
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning(f"visual_selector: history {p.name} unreadable — treating as empty")
        return []
    used = data.get("used", []) if isinstance(data, dict) else []
    return [u for u in used if isinstance(u, str)]


def _save_history(path, used, keep):
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps({"used": used[-keep:]}, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(p)


def pick_direction(rng: random.Random = None) -> dict:
    """Choose a thumbnail direction obeying the not-consecutive / max-2-in-6 rule.

    Returns {id, subject, image_rules}.
    """
    rng = rng or random
    directions = _read_json(THUMBNAIL_DIRECTIONS_FILE, "directions")
    by_id = {d["id"]: d for d in directions if d.get("id")}
    history = _load_history(THUMBNAIL_DIRECTION_HISTORY_FILE)

    last = history[-1] if history else None
    window = history[-_DIR_WINDOW:]

    def _eligible(did):
        if did == last:
            return False  # not twice in a row
        if window.count(did) >= _DIR_MAX_IN_WINDOW:
            return False  # not more than twice in the last 6
        return True

    candidates = [d for d in directions if _eligible(d["id"])]
    if not candidates:
        # Relax to just the not-consecutive rule, then to anything.
        candidates = [d for d in directions if d["id"] != last] or directions
        log.info("visual_selector: direction rule relaxed (small pool / dense history)")

    choice = rng.choice(candidates)
    history.append(choice["id"])
    _save_history(THUMBNAIL_DIRECTION_HISTORY_FILE, history, keep=_DIR_WINDOW * 4)
    log.info(f"visual_selector: thumbnail direction '{choice['id']}'")
    return {"id": choice["id"], "subject": choice.get("subject", ""),
            "image_rules": choice.get("image_rules", "")}


def pick_title_template(rng: random.Random = None) -> str:
    """Choose a title template not used within the last TITLE_HISTORY_WINDOW picks."""
    rng = rng or random
    templates = _read_json(TITLE_TEMPLATES_FILE, "templates")
    history = _load_history(TITLE_HISTORY_FILE)
    recent = set(history[-TITLE_HISTORY_WINDOW:])

    candidates = [t for t in templates if t not in recent]
    if not candidates:
        candidates = [t for t in templates if t != (history[-1] if history else None)] or templates
        log.info("visual_selector: title window relaxed (pool <= window)")

    choice = rng.choice(candidates)
    history.append(choice)
    _save_history(TITLE_HISTORY_FILE, history, keep=TITLE_HISTORY_WINDOW * 3)
    log.info(f"visual_selector: title template -> {choice[:48]}...")
    return choice
