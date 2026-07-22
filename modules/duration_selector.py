"""Weighted duration-bucket selector.

RECOVERY PIPELINE v3 — Phase 2. Randomises each upload's length across three
weighted buckets (config.DURATION_BUCKETS) so the catalogue stops being a wall
of identical 30-minute mixes. Returns concrete pipeline parameters:

  - target_minutes: the sampled target length
  - gen_count:      how many FRESH generations to run (each ≈ 2 songs ≈ 6 min)
  - archive_count:  how many archived songs to top up with to hit the target

Each aimusicfactory song is ~3 min, so a fresh generation (2 songs) is ~6 min.
Fresh audio always leads; the archive only tops up longer targets, keeping
generation cost bounded while still reaching 30-45 min lengths.
"""
import json
import logging
import random
from pathlib import Path

from config import DURATION_BUCKETS, DURATION_HISTORY_FILE

log = logging.getLogger("music_pipeline")

_MIN_PER_SONG = 3          # ~3 min per merged aimusicfactory song
_SONGS_PER_GEN = 2         # each "Generate" click yields 2 songs
_MIN_PER_GEN = _MIN_PER_SONG * _SONGS_PER_GEN  # ~6 min of fresh audio per gen


def choose_bucket(rng: random.Random = None) -> tuple:
    """Pick (label, min_minutes, max_minutes) by weight."""
    rng = rng or random
    labels = [b[0] for b in DURATION_BUCKETS]
    weights = [b[3] for b in DURATION_BUCKETS]
    idx = rng.choices(range(len(DURATION_BUCKETS)), weights=weights, k=1)[0]
    label, lo, hi, _ = DURATION_BUCKETS[idx]
    return label, lo, hi


def _plan_for_minutes(target: int) -> tuple:
    """Map a target length to (gen_count, archive_count).

    Cap fresh generation at ~4 gens (24 min of fresh audio) to bound cost, then
    top up the remainder from the archive. Short targets use fresh only.
    """
    total_songs = max(1, round(target / _MIN_PER_SONG))
    max_fresh_gens = 4
    fresh_gens = min(max_fresh_gens, max(1, round(total_songs / _SONGS_PER_GEN)))
    fresh_songs = fresh_gens * _SONGS_PER_GEN
    archive_count = max(0, total_songs - fresh_songs)
    return fresh_gens, archive_count


def pick_duration(rng: random.Random = None) -> dict:
    """Sample a bucket and a concrete length, returning a pipeline plan.

    Returns {bucket, target_minutes, gen_count, archive_count}. Logs the choice
    and appends it to the persistent duration history for later measurement.
    """
    rng = rng or random
    label, lo, hi = choose_bucket(rng)
    target = rng.randint(lo, hi)
    gen_count, archive_count = _plan_for_minutes(target)

    plan = {
        "bucket": label,
        "target_minutes": target,
        "gen_count": gen_count,
        "archive_count": archive_count,
    }
    _record(plan)
    log.info(
        f"duration_selector: bucket '{label}' → ~{target} min "
        f"({gen_count} fresh gen(s) + {archive_count} archived)"
    )
    return plan


def _record(plan: dict) -> None:
    path = Path(DURATION_HISTORY_FILE)
    try:
        history = []
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            history = data.get("picks", []) if isinstance(data, dict) else []
        history.append(plan)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps({"picks": history[-500:]}, indent=2), encoding="utf-8")
        tmp.replace(path)
    except (OSError, json.JSONDecodeError) as e:
        log.warning(f"duration_selector: could not record pick: {e}")
