"""Audio-prompt pool with a persistent non-repetition history.

RECOVERY PIPELINE v3 — Phase 2. The old pipeline fed every generation the same
fixed style prompt, which made the whole catalogue sound like one product. This
module loads a pool of structurally distinct prompts (prompts/pool.json) and
picks one per generation, never repeating a prompt used in the last
PROMPT_HISTORY_WINDOW uploads. The chosen prompt id is logged and remembered on
disk so the rule survives restarts.
"""
import json
import logging
import random
from pathlib import Path

from config import (
    PROMPT_POOL_FILE,
    PROMPT_HISTORY_FILE,
    PROMPT_HISTORY_WINDOW,
)

log = logging.getLogger("music_pipeline")


def load_pool() -> list:
    """Return the list of {id, prompt} entries from the pool file."""
    path = Path(PROMPT_POOL_FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"prompt_pool: cannot read {path}: {e}")
    entries = data.get("prompts", [])
    out = []
    for e in entries:
        if isinstance(e, dict) and e.get("prompt"):
            out.append({"id": e.get("id") or e["prompt"][:24], "prompt": e["prompt"]})
    if not out:
        raise RuntimeError(f"prompt_pool: {path} has no usable prompts")
    return out


def _load_history() -> list:
    path = Path(PROMPT_HISTORY_FILE)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("prompt_pool: history unreadable — treating as empty")
        return []
    ids = data.get("used_ids", []) if isinstance(data, dict) else []
    return [i for i in ids if isinstance(i, str)]


def _save_history(used_ids: list) -> None:
    path = Path(PROMPT_HISTORY_FILE)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # Keep a little more than the window so the rule is stable across restarts.
    keep = used_ids[-(PROMPT_HISTORY_WINDOW * 3):]
    tmp.write_text(json.dumps({"used_ids": keep}, indent=2), encoding="utf-8")
    tmp.replace(path)


def pick_prompt(rng: random.Random = None) -> dict:
    """Choose a prompt not used in the last PROMPT_HISTORY_WINDOW picks.

    Records the choice in the persistent history and returns {id, prompt}.
    `rng` is injectable for deterministic tests.
    """
    rng = rng or random
    pool = load_pool()
    history = _load_history()
    recent = set(history[-PROMPT_HISTORY_WINDOW:])

    candidates = [e for e in pool if e["id"] not in recent]
    if not candidates:
        # Pool smaller than / equal to the window, or all recently used —
        # fall back to the least-recently-used prompts so we still rotate.
        lru = [e for e in pool if e["id"] not in set(history[-1:])] or pool
        candidates = lru
        log.info("prompt_pool: all prompts recently used — relaxing window")

    choice = rng.choice(candidates)
    history.append(choice["id"])
    _save_history(history)
    log.info(
        f"prompt_pool: selected '{choice['id']}' "
        f"(pool {len(pool)}, window {PROMPT_HISTORY_WINDOW})"
    )
    return choice
