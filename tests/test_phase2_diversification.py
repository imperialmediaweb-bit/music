"""QA for RECOVERY PIPELINE v3 Phase 2 — audio diversification.

Covers the prompt pool (size, unique ids, length cap, non-repetition within the
window, persistence across restart) and the weighted duration buckets
(distribution, in-range targets, sane gen/archive plans).
"""
import random
from collections import Counter

import pytest

from modules import prompt_pool, duration_selector


@pytest.fixture
def pools(tmp_path, monkeypatch):
    monkeypatch.setattr(prompt_pool, "PROMPT_HISTORY_FILE", tmp_path / "ph.json")
    monkeypatch.setattr(prompt_pool, "PROMPT_HISTORY_WINDOW", 8)
    monkeypatch.setattr(duration_selector, "DURATION_HISTORY_FILE", tmp_path / "dh.json")
    return prompt_pool, duration_selector


def test_pool_is_large_unique_and_bounded(pools):
    pool = prompt_pool.load_pool()
    ids = [p["id"] for p in pool]
    assert len(pool) >= 15
    assert len(set(ids)) == len(ids)
    assert all(len(p["prompt"]) <= 980 for p in pool)


def test_no_repetition_within_window(pools):
    rng = random.Random(42)
    seq = [prompt_pool.pick_prompt(rng=rng)["id"] for _ in range(200)]
    window = 8
    for i in range(len(seq)):
        assert seq[i] not in seq[max(0, i - window):i]


def test_history_persists_across_restart(pools):
    rng = random.Random(1)
    seq = [prompt_pool.pick_prompt(rng=rng)["id"] for _ in range(20)]
    last8 = set(seq[-8:])
    # Fresh RNG = simulated new process; the on-disk history must still apply.
    nxt = prompt_pool.pick_prompt(rng=random.Random(999))["id"]
    assert nxt not in last8


def test_duration_distribution_matches_weights(pools):
    rng = random.Random(123)
    counts = Counter()
    ranges = {"short": (4, 8), "medium": (15, 25), "long": (30, 45)}
    for _ in range(3000):
        plan = duration_selector.pick_duration(rng=rng)
        counts[plan["bucket"]] += 1
        lo, hi = ranges[plan["bucket"]]
        assert lo <= plan["target_minutes"] <= hi
        assert plan["gen_count"] >= 1 and plan["archive_count"] >= 0
    total = sum(counts.values())
    pct = {k: 100 * v / total for k, v in counts.items()}
    assert abs(pct["short"] - 20) < 4
    assert abs(pct["medium"] - 30) < 4
    assert abs(pct["long"] - 50) < 4
