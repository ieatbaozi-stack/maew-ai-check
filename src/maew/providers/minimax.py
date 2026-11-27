"""MiniMax Coding Plan usage provider (5h / 7d).

Security:
- Sends the API key ONLY to the configured region host (international or china).
- Never follows HTTP 3xx redirects (allow_redirects=False) so the bearer key
  can never be forwarded to an unexpected host.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Callable

import requests

from ..models import SnapshotStatus, UsageMetric, UsageSnapshot
from .base import Provider

MINIMAX_REGIONS = {
    "international": "https://api.minimax.io",
    "china": "https://api.minimax.cn",
}
_QUOTA_PATH = "/v1/token_plan/remains"
_STATUS_LIMITED = 1
_STATUS_EXHAUSTED = 2
_STATUS_UNLIMITED = 3


def _num(val: object) -> float | None:
    if isinstance(val, bool) or val is None:
        return None
    try:
        n = float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def _epoch_to_local(val: object) -> datetime | None:
    n = _num(val)
    if n is None or n <= 0:
        return None
    secs = n if n < 1e12 else n / 1000.0
    try:
        return datetime.fromtimestamp(secs)
    except (OverflowError, OSError, ValueError):
        return None


def _pct_used(row: dict[str, Any], prefix: str) -> float | None:
    rem = _num(row.get(f"{prefix}_remaining_percent"))
    if rem is None:
        count = _num(row.get(f"{prefix}_usage_count"))
        total = _num(row.get(f"{prefix}_total_count"))
        if count is None or total is None or total <= 0:
            return None
        rem = (count / total) * 100.0
    return max(0.0, min(100.0, 100.0 - rem))


def _select_row(payload: dict[str, Any]) -> dict[str, Any] | None:
    remains = payload.get("model_remains")
    if not isinstance(remains, list):
        return None
    valid = []
    for r in remains:
        if not isinstance(r, dict):
            continue
        if (
            _num(r.get("current_interval_status")) == _STATUS_UNLIMITED
            and _num(r.get("current_weekly_status")) == _STATUS_UNLIMITED
            and _num(r.get("current_interval_total_count")) == 0
            and _num(r.get("current_weekly_total_count")) == 0
        ):
            continue
        valid.append(r)
    for r in valid:
        name = str(r.get("model_name") or "").strip().lower()
        if name == "general" or name.startswith("minimax-m"):
            return r
    return valid[0] if valid else None


def _window_metric(
    row: dict[str, Any],
    *,
    label: str,
    hours: float,
    prefix: str,
    status_key: str,
    end_key: str,
) -> UsageMetric | None:
    st = _num(row.get(status_key))
    if st == _STATUS_UNLIMITED:
        return UsageMetric(
            label=label,
            percent_used=0.0,
            reset_label="unlimited",
            window_hours=hours,
            group="MiniMax",
        )
    if st == _STATUS_EXHAUSTED:
        pct: float | None = 100.0
    else:
        pct = _pct_used(row, prefix)
    if pct is None:
        return None
    resets_at = _epoch_to_local(row.get(end_key))
    return UsageMetric(
        label=label,
        percent_used=pct,
        resets_at=resets_at,
        reset_label="idle" if pct == 0.0 and resets_at is None else None,
        window_hours=hours,
        group="MiniMax",
    )


def build_minimax_snapshot(payload: dict[str, Any]) -> UsageSnapshot:
    base = payload.get("base_resp")
    if isinstance(base, dict):
        code = int(_num(base.get("status_code")) or 0)
        if code == 1004:
            return UsageSnapshot(
                provider="minimax",
                display_name="MiniMax",
                status=SnapshotStatus.AUTH_REQUIRED,
                error="MiniMax rejected the API key",
            )
        if code == 2049:
            return UsageSnapshot(
                provider="minimax",
                display_name="MiniMax",
                status=SnapshotStatus.AUTH_REQUIRED,
                error="MiniMax key belongs to the other region (switch region in Settings)",
            )
        if code != 0:
            return UsageSnapshot(
                provider="minimax",
                display_name="MiniMax",
                status=SnapshotStatus.ERROR,
                error=f"MiniMax API error {code}",
            )

    row = _select_row(payload)
    if row is None:
        return UsageSnapshot(
            provider="minimax",
            display_name="MiniMax",
            status=SnapshotStatus.ERROR,
            error="Could not read MiniMax Coding Plan quota",
        )

    metrics: list[UsageMetric] = []
    m5h = _window_metric(
        row,
        label="5h",
        hours=5.0,
        prefix="current_interval",
        status_key="current_interval_status",
        end_key="end_time",
    )
    if m5h is not None:
        metrics.append(m5h)

    m7d = _window_metric(
        row,
        label="7d",
        hours=168.0,
        prefix="current_weekly",
        status_key="current_weekly_status",
        end_key="weekly_end_time",
    )
    if m7d is not None:
        metrics.append(m7d)

    if not metrics:
        return UsageSnapshot(
            provider="minimax",
            display_name="MiniMax",
            status=SnapshotStatus.ERROR,
            error="MiniMax response missing usage windows",
        )

    return UsageSnapshot(
        provider="minimax",
        display_name="MiniMax",
        status=SnapshotStatus.OK,
        metrics=metrics,
    )


class MiniMaxProvider(Provider):
    id = "minimax"
    display_name = "MiniMax"
    short_label = "MM"
    kind = "api_key"

    def __init__(
        self,
        *,
        key_loader: Callable[[], str | None],
        region: str = "international",
    ) -> None:
        self._key_loader = key_loader
        self.region = region if region in MINIMAX_REGIONS else "international"

    def fetch(self) -> UsageSnapshot:
        api_key = self._key_loader()
        if not api_key:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.AUTH_REQUIRED,
                error="Add a MiniMax Coding Plan API key in Settings",
            )
        host = MINIMAX_REGIONS[self.region]
        try:
            r = requests.get(
                f"{host}{_QUOTA_PATH}",
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                timeout=15,
                allow_redirects=False,
            )
            if 300 <= r.status_code < 400:
                return UsageSnapshot(
                    provider=self.id,
                    display_name=self.display_name,
                    status=SnapshotStatus.ERROR,
                    error=f"MiniMax refused redirect (HTTP {r.status_code}) for key safety",
                )
            if r.status_code in (401, 403):
                return UsageSnapshot(
                    provider=self.id,
                    display_name=self.display_name,
                    status=SnapshotStatus.AUTH_REQUIRED,
                    error="MiniMax rejected the API key",
                )
            r.raise_for_status()
            payload = r.json()
            if not isinstance(payload, dict):
                raise ValueError("Unexpected MiniMax response")
            return build_minimax_snapshot(payload)
        except requests.RequestException as exc:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=f"MiniMax request failed: {exc}",
            )
        except ValueError as exc:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=str(exc),
            )
