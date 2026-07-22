"""QA simulation for the RECOVERY PIPELINE v3 Phase-1 upload guard.

Gate 2 requires: run 14 simulated days at accelerated time and confirm EXACTLY
the scheduled number of uploads, on the correct days, with no duplicates — even
across a simulated process restart.

The guard's public functions accept an injectable `now`, so the whole 14-day
run is driven deterministically without real waiting.
"""
from datetime import datetime, timedelta

import pytest

from modules import upload_guard


@pytest.fixture
def guard(tmp_path, monkeypatch):
    """Point the guard at a throwaway history file with the real Phase-1 limits."""
    hist = tmp_path / "upload_history.json"
    monkeypatch.setattr(upload_guard, "UPLOAD_HISTORY_FILE", hist)
    monkeypatch.setattr(upload_guard, "MAX_UPLOADS_PER_WEEK", 3)
    monkeypatch.setattr(upload_guard, "MIN_HOURS_BETWEEN_UPLOADS", 24)
    return upload_guard


def _tue_thu_sat_1700(start: datetime, days: int):
    """Yield every Tue/Thu/Sat 17:00 slot in the window (APScheduler firings)."""
    for d in range(days):
        day = start + timedelta(days=d)
        if day.weekday() in (1, 3, 5):  # Mon=0 … Tue=1, Thu=3, Sat=5
            yield day.replace(hour=17, minute=0, second=0, microsecond=0)


def test_14_day_simulation_exactly_six_uploads(guard):
    # Start on a Monday so the window is aligned and deterministic.
    start = datetime(2026, 7, 6, 0, 0, 0)  # 2026-07-06 is a Monday
    assert start.weekday() == 0

    fired, uploaded = 0, 0
    for slot in _tue_thu_sat_1700(start, 14):
        fired += 1
        allowed, _ = guard.can_upload(now=slot)
        if allowed:
            guard.record_upload(title=f"track-{slot:%Y-%m-%d}", now=slot)
            uploaded += 1

    # 14 days from Monday covers Tue/Thu/Sat twice = 6 slots, all allowed.
    assert fired == 6
    assert uploaded == 6


def test_restart_same_slot_is_not_duplicated(guard):
    slot = datetime(2026, 7, 7, 17, 0, 0)  # Tuesday
    allowed, _ = guard.can_upload(now=slot)
    assert allowed
    guard.record_upload(title="first", now=slot)

    # Simulate a process restart that re-fires the SAME slot 30 min later.
    retry = slot + timedelta(minutes=30)
    allowed, reason = guard.can_upload(now=retry)
    assert not allowed
    assert "minimum gap" in reason


def test_weekly_cap_blocks_the_fourth(guard):
    base = datetime(2026, 7, 7, 17, 0, 0)  # ISO week of Mon 2026-07-06
    # Three uploads spaced 24h+ apart, all in the same calendar week — allowed.
    for i in range(3):
        when = base + timedelta(hours=25 * i)
        allowed, _ = guard.can_upload(now=when)
        assert allowed, f"upload {i + 1} should be allowed"
        guard.record_upload(title=f"t{i}", now=when)

    # A 4th in the SAME calendar week must be blocked by the cap.
    fourth = base + timedelta(hours=25 * 3)
    allowed, reason = guard.can_upload(now=fourth)
    assert not allowed
    assert "calendar week" in reason


def test_cap_resets_next_calendar_week(guard):
    base = datetime(2026, 7, 7, 17, 0, 0)  # week of Mon 2026-07-06
    for i in range(3):
        guard.record_upload(title=f"t{i}", now=base + timedelta(hours=25 * i))

    # The following ISO week (Mon 2026-07-13) resets the cap.
    later = datetime(2026, 7, 14, 17, 0, 0)
    allowed, _ = guard.can_upload(now=later)
    assert allowed


def test_boundary_slot_exactly_seven_days_later_is_allowed(guard):
    # The bug a rolling 7-day window would cause: Tue→Tue is exactly 7 days,
    # and the previous week's 3 slots must NOT block the new week's first slot.
    for d in (datetime(2026, 7, 7, 17, 0),   # Tue
              datetime(2026, 7, 9, 17, 0),   # Thu
              datetime(2026, 7, 11, 17, 0)):  # Sat
        guard.record_upload(title=str(d), now=d)
    next_tue = datetime(2026, 7, 14, 17, 0)  # exactly 7 days after first
    allowed, _ = guard.can_upload(now=next_tue)
    assert allowed


def test_corrupt_history_is_treated_as_empty(guard):
    guard.UPLOAD_HISTORY_FILE.write_text("{ this is not valid json", encoding="utf-8")
    allowed, _ = guard.can_upload(now=datetime(2026, 7, 7, 17, 0, 0))
    assert allowed  # unreadable history must not permanently block uploads
