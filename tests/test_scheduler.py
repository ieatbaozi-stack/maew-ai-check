from __future__ import annotations

from datetime import datetime, timedelta

from maew.models import SnapshotStatus, UsageMetric, UsageSnapshot
from maew.scheduler import AdaptiveScheduler, adaptive_refresh_minutes


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
