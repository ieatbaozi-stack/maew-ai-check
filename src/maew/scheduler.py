"""Adaptive refresh scheduler (active cadence + exponential idle backoff + reset pull-forward)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import SnapshotStatus, UsageSnapshot

ACTIVE_MODE_MINUTES = 30
STALE_ERROR_RETRY_MINUTES = 1


def adaptive_refresh_minutes(
    *,
    active: bool,
    active_minutes: int,
    unchanged_cycles: int,
    max_minutes: int,
) -> int:
    active_minutes = max(1, min(active_minutes, max_minutes))
    if active:
        return active_minutes
    backoff = active_minutes * (2 ** max(0, unchanged_cycles))
    return min(max_minutes, backoff)


def snapshot_signature(snapshot: UsageSnapshot) -> tuple:
    return (
        snapshot.status.value,
        snapshot.error,
        tuple(
            (
                m.label,
                round(m.percent_used, 1) if m.percent_used is not None else None,
                m.reset_label,
            )
            for m in snapshot.metrics
        ),
    )


def earliest_reset_refresh_time(
    snapshots: dict[str, UsageSnapshot],
    now: datetime | None = None,
) -> datetime | None:
    now = now or datetime.now()
    grace = timedelta(minutes=1)
    earliest: datetime | None = None
    for snap in snapshots.values():
        if snap.status != SnapshotStatus.OK:
            continue
        for metric in snap.metrics:
            if metric.resets_at is None or (metric.percent_used or 0) <= 0:
                continue
            target = metric.resets_at + grace
            if target <= now:
                continue
            if earliest is None or target < earliest:
                earliest = target
    return earliest


@dataclass
class ScheduleDecision:
    next_refresh_at: datetime
    delay_seconds: float
    interval_minutes: int
    active: bool


class AdaptiveScheduler:
    """Computes safe refresh delays without hammering providers or burning quota."""

    def __init__(self, active_minutes: int = 5, max_minutes: int = 60):
        self.active_minutes = active_minutes
        self.max_minutes = max_minutes
        self._active_until = datetime.now() + timedelta(minutes=ACTIVE_MODE_MINUTES)
        self._unchanged_cycles = 0
        self._last_signatures: dict[str, tuple] | None = None

    def mark_manual_activity(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        self._active_until = now + timedelta(minutes=ACTIVE_MODE_MINUTES)
        self._unchanged_cycles = 0

    def record_cycle(
        self,
        snapshots: dict[str, UsageSnapshot],
        *,
        manual: bool,
        now: datetime | None = None,
    ) -> ScheduleDecision:
        now = now or datetime.now()
        current_sigs = {k: snapshot_signature(v) for k, v in snapshots.items()}
        changed = self._last_signatures is None or current_sigs != self._last_signatures
        self._last_signatures = current_sigs

        if changed or manual:
            self._active_until = now + timedelta(minutes=ACTIVE_MODE_MINUTES)
            self._unchanged_cycles = 0
        else:
            self._unchanged_cycles += 1

        return self.next_decision(snapshots, now=now)

    def next_decision(
        self,
        snapshots: dict[str, UsageSnapshot],
        *,
        now: datetime | None = None,
    ) -> ScheduleDecision:
        now = now or datetime.now()
        active = now < self._active_until
        minutes = adaptive_refresh_minutes(
            active=active,
            active_minutes=self.active_minutes,
            unchanged_cycles=self._unchanged_cycles,
            max_minutes=self.max_minutes,
        )
        next_at = now + timedelta(minutes=minutes)

        soon_reset = earliest_reset_refresh_time(snapshots, now=now)
        if soon_reset is not None and soon_reset < next_at:
            next_at = soon_reset

        has_stale_error = any(
            s.status == SnapshotStatus.ERROR and s.stale for s in snapshots.values()
        )
        if has_stale_error:
            retry_at = now + timedelta(minutes=STALE_ERROR_RETRY_MINUTES)
            if retry_at < next_at:
                next_at = retry_at

        delay_s = max(10.0, (next_at - now).total_seconds())
        effective_min = max(1, int(round(delay_s / 60.0)))
        return ScheduleDecision(
            next_refresh_at=next_at,
            delay_seconds=delay_s,
            interval_minutes=effective_min,
            active=active,
        )
