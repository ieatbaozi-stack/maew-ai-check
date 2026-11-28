"""Adaptive refresh scheduler (active cadence + exponential idle backoff + reset pull-forward)."""

from __future__ import annotations

import ctypes
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import SnapshotStatus, UsageSnapshot

ACTIVE_MODE_MINUTES = 30
STALE_ERROR_RETRY_MINUTES = 1
DEFAULT_IDLE_THRESHOLD_SECONDS = 300.0  # 5 min without OS input counts as idle
DEFAULT_ACTIVE_RESUME_SECONDS = 15.0    # OS input within last 15s counts as active return
DEFAULT_WAKE_COOLDOWN_SECONDS = 60.0    # minimum gap between auto-wake refreshes


def get_os_idle_seconds() -> float | None:
    """Return seconds since last Windows keyboard/mouse input via GetLastInputInfo.

    Privacy: reads only the OS last-input tick timestamp — never installs input
    hooks or inspects keys, mouse coordinates, or active windows.
    """
    if sys.platform != "win32":
        return None
    try:
        class _LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint32)]

        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        tick = ctypes.windll.kernel32.GetTickCount()
        elapsed_ms = (int(tick) - int(info.dwTime)) & 0xFFFFFFFF
        return elapsed_ms / 1000.0
    except Exception:  # noqa: BLE001
        return None


class IdleReturnDetector:
    """Detects when the user returns after OS idle or Windows sleep/hibernate."""

    def __init__(
        self,
        *,
        idle_threshold_seconds: float = DEFAULT_IDLE_THRESHOLD_SECONDS,
        active_resume_seconds: float = DEFAULT_ACTIVE_RESUME_SECONDS,
        cooldown_seconds: float = DEFAULT_WAKE_COOLDOWN_SECONDS,
    ) -> None:
        self.idle_threshold_seconds = idle_threshold_seconds
        self.active_resume_seconds = active_resume_seconds
        self.cooldown_seconds = cooldown_seconds
        self._was_idle = False
        self._last_wall: datetime | None = None
        self._last_mono: float | None = None
        self._last_wake_mono: float | None = None

    def check(
        self,
        *,
        idle_seconds: float | None,
        now_wall: datetime | None = None,
        now_mono: float | None = None,
        last_refresh_at: datetime | None = None,
    ) -> str | None:
        """Return 'idle_return' or 'system_wake' when an automatic refresh should fire."""
        now_wall = now_wall or datetime.now()
        now_mono = time.monotonic() if now_mono is None else now_mono

        reason: str | None = None

        if self._last_wall is not None and self._last_mono is not None:
            wall_delta = (now_wall - self._last_wall).total_seconds()
            mono_delta = now_mono - self._last_mono
            if wall_delta - mono_delta >= 60.0:
                reason = "system_wake"
        self._last_wall = now_wall
        self._last_mono = now_mono

        if idle_seconds is not None:
            if idle_seconds >= self.idle_threshold_seconds:
                self._was_idle = True
            elif self._was_idle and idle_seconds <= self.active_resume_seconds:
                self._was_idle = False
                if reason is None:
                    reason = "idle_return"

        if reason is None:
            return None

        if (
            self._last_wake_mono is not None
            and (now_mono - self._last_wake_mono) < self.cooldown_seconds
        ):
            return None
        if (
            last_refresh_at is not None
            and (now_wall - last_refresh_at).total_seconds() < self.cooldown_seconds
        ):
            return None

        self._last_wake_mono = now_mono
        return reason


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
