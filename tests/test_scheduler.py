from __future__ import annotations

from datetime import datetime, timedelta

from maew.models import SnapshotStatus, UsageMetric, UsageSnapshot
from maew.scheduler import AdaptiveScheduler, IdleReturnDetector, adaptive_refresh_minutes


def test_adaptive_backoff_curve():
    assert adaptive_refresh_minutes(active=True, active_minutes=5, unchanged_cycles=4, max_minutes=60) == 5
    assert adaptive_refresh_minutes(active=False, active_minutes=5, unchanged_cycles=0, max_minutes=60) == 5
    assert adaptive_refresh_minutes(active=False, active_minutes=5, unchanged_cycles=1, max_minutes=60) == 10
    assert adaptive_refresh_minutes(active=False, active_minutes=5, unchanged_cycles=2, max_minutes=60) == 20
    assert adaptive_refresh_minutes(active=False, active_minutes=5, unchanged_cycles=5, max_minutes=60) == 60


def test_scheduler_pulls_forward_before_quota_reset():
    now = datetime(2026, 11, 27, 12, 0, 0)
    sched = AdaptiveScheduler(active_minutes=5, max_minutes=60)
    # Force idle backoff state
    sched._active_until = now - timedelta(minutes=1)
    sched._unchanged_cycles = 4  # would normally wait 60m

    snap = UsageSnapshot(
        provider="antigravity",
        display_name="Antigravity",
        status=SnapshotStatus.OK,
        metrics=[
            UsageMetric(
                label="Gemini 5h",
                percent_used=80.0,
                resets_at=now + timedelta(minutes=12),
            )
        ],
    )
    decision = sched.next_decision({"antigravity": snap}, now=now)
    # Should pull forward to resets_at + 1 min = 13 min instead of 60 min!
    assert 12 * 60 <= decision.delay_seconds <= 14 * 60


def test_idle_return_detector_triggers_after_afk_and_respects_cooldown():
    t0 = datetime(2026, 11, 28, 10, 0, 0)
    det = IdleReturnDetector(idle_threshold_seconds=300.0, active_resume_seconds=15.0, cooldown_seconds=60.0)

    # Normal active usage: never triggers
    assert det.check(idle_seconds=2.0, now_wall=t0, now_mono=100.0, last_refresh_at=t0 - timedelta(minutes=10)) is None
    # Short 2-minute pause then move mouse: below 5m threshold, should NOT trigger
    assert det.check(idle_seconds=120.0, now_wall=t0 + timedelta(minutes=2), now_mono=220.0, last_refresh_at=t0 - timedelta(minutes=10)) is None
    assert det.check(idle_seconds=0.5, now_wall=t0 + timedelta(minutes=2, seconds=5), now_mono=225.0, last_refresh_at=t0 - timedelta(minutes=10)) is None

    # User goes AFK for 6 minutes, then moves mouse -> triggers idle_return!
    t_afk = t0 + timedelta(minutes=8)
    assert det.check(idle_seconds=360.0, now_wall=t_afk, now_mono=580.0, last_refresh_at=t0) is None
    assert det.check(idle_seconds=0.2, now_wall=t_afk + timedelta(seconds=2), now_mono=582.0, last_refresh_at=t0) == "idle_return"

    # Second check immediately after stays quiet (flag cleared + cooldown active)
    assert det.check(idle_seconds=0.5, now_wall=t_afk + timedelta(seconds=4), now_mono=584.0, last_refresh_at=t0) is None


def test_idle_return_detector_skips_if_just_refreshed():
    t0 = datetime(2026, 11, 28, 10, 0, 0)
    det = IdleReturnDetector(idle_threshold_seconds=300.0, active_resume_seconds=15.0, cooldown_seconds=60.0)
    assert det.check(idle_seconds=400.0, now_wall=t0, now_mono=100.0, last_refresh_at=t0 - timedelta(seconds=20)) is None
    # Refreshed only 22s ago -> skip duplicate fetch
    assert det.check(idle_seconds=0.1, now_wall=t0 + timedelta(seconds=2), now_mono=102.0, last_refresh_at=t0 - timedelta(seconds=20)) is None


def test_idle_return_detector_detects_sleep_wake_wall_clock_jump():
    t0 = datetime(2026, 11, 28, 10, 0, 0)
    det = IdleReturnDetector(idle_threshold_seconds=300.0, active_resume_seconds=15.0, cooldown_seconds=60.0)
    assert det.check(idle_seconds=1.0, now_wall=t0, now_mono=100.0, last_refresh_at=t0) is None
    # PC slept for 45 minutes: wall clock jumps 45m while monotonic clock barely advances
    assert det.check(idle_seconds=0.5, now_wall=t0 + timedelta(minutes=45), now_mono=102.0, last_refresh_at=t0) == "system_wake"
