"""QA for RECOVERY PIPELINE v3 Phase 3 — visual + title diversification.

Covers the six thumbnail directions (count, distinctness, the not-consecutive /
max-2-in-6 rotation rule, restart persistence) and the title templates
(count, no-emoji/question variety, non-repetition window, placeholder filling).
"""
import random
from collections import Counter

import pytest

from modules import visual_selector as vs
import config


@pytest.fixture
def sel(tmp_path, monkeypatch):
    monkeypatch.setattr(vs, "THUMBNAIL_DIRECTION_HISTORY_FILE", tmp_path / "dir.json")
    monkeypatch.setattr(vs, "TITLE_HISTORY_FILE", tmp_path / "tit.json")
    monkeypatch.setattr(vs, "TITLE_HISTORY_WINDOW", 5)
    return vs


def test_six_distinct_directions(sel):
    dirs = sel._read_json(config.THUMBNAIL_DIRECTIONS_FILE, "directions")
    ids = [d["id"] for d in dirs]
    assert len(dirs) == 6
    assert len(set(ids)) == 6
    assert all(d.get("subject") and d.get("image_rules") for d in dirs)


def test_direction_rotation_rule(sel):
    rng = random.Random(3)
    seq = [sel.pick_direction(rng=rng)["id"] for _ in range(120)]
    # never twice in a row
    assert all(seq[i] != seq[i - 1] for i in range(1, len(seq)))
    # never more than twice in any window of 6
    worst = max(
        Counter(seq[i:i + 6]).most_common(1)[0][1]
        for i in range(0, len(seq) - 6)
    )
    assert worst <= 2


def test_direction_persists_across_restart(sel):
    rng = random.Random(3)
    seq = [sel.pick_direction(rng=rng)["id"] for _ in range(10)]
    nxt = sel.pick_direction(rng=random.Random(50))["id"]
    assert nxt != seq[-1]


def test_title_templates_have_variety(sel):
    tpls = sel._read_json(config.TITLE_TEMPLATES_FILE, "templates")
    assert len(tpls) >= 8
    assert len(set(tpls)) == len(tpls)
    assert len([t for t in tpls if "🔥" not in t]) >= 3  # no-emoji variants
    assert any("?" in t for t in tpls)                    # a question variant


def test_title_non_repetition(sel):
    rng = random.Random(9)
    seq = [sel.pick_title_template(rng=rng) for _ in range(120)]
    window = 5
    for i in range(len(seq)):
        assert seq[i] not in seq[max(0, i - window):i]


def test_title_placeholders_fill(sel):
    t = sel.pick_title_template(rng=random.Random(1)).format(
        genre="Afro House", genre_hashtag="#afrohouse", mix_number=42
    )
    assert "{" not in t and "}" not in t
