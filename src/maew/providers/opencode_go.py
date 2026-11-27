"""OpenCode Go usage provider via official OpenCode API (5h / 7d / 30d)."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Callable

import requests

from ..models import SnapshotStatus, UsageMetric, UsageSnapshot
from .base import Provider

OPENCODE_GO_USAGE_API = "https://opencode.ai/zen/go/v1/usage"

_WINDOWS = (
    ("rolling", "5h", 5.0),
    ("weekly", "7d", 168.0),
    ("monthly", "30d", 720.0),
)


def _parse_iso_local(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def build_opencode_snapshot(payload: dict[str, Any]) -> UsageSnapshot:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("OpenCode response missing usage object")

    metrics: list[UsageMetric] = []
    for key, label, hours in _WINDOWS:
        row = usage.get(key)
        if not isinstance(row, dict):
            continue
        raw_pct = row.get("percent")
        if isinstance(raw_pct, bool) or not isinstance(raw_pct, (int, float)):
            continue
        pct = float(raw_pct)
        if not math.isfinite(pct):
            continue
        status = str(row.get("status") or "").lower()
        if status == "rate-limited":
            pct = max(100.0, pct)
        pct = max(0.0, min(100.0, pct))
        resets_at = _parse_iso_local(row.get("resetsAt"))
        metrics.append(
            UsageMetric(
                label=label,
                percent_used=pct,
                resets_at=resets_at,
                reset_label="idle" if pct == 0.0 and resets_at is None else None,
                note="Rate limit reached" if status == "rate-limited" else None,
                window_hours=hours,
                group="OpenCode",
            )
        )

    if not metrics:
        raise ValueError("OpenCode response contained no readable usage windows")

    return UsageSnapshot(
        provider="opencode_go",
        display_name="OpenCode",
        status=SnapshotStatus.OK,
        metrics=metrics,
    )


class OpenCodeGoProvider(Provider):
    id = "opencode_go"
    display_name = "OpenCode"
    short_label = "OC"
    kind = "api_key"

    def __init__(self, *, key_loader: Callable[[], str | None]) -> None:
        self._key_loader = key_loader

    def fetch(self) -> UsageSnapshot:
        api_key = self._key_loader()
        if not api_key:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.AUTH_REQUIRED,
                error="Add an OpenCode Go API key in Settings",
            )
        try:
            r = requests.get(
                OPENCODE_GO_USAGE_API,
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                timeout=15,
                allow_redirects=False,
            )
            if 300 <= r.status_code < 400:
                return UsageSnapshot(
                    provider=self.id,
                    display_name=self.display_name,
                    status=SnapshotStatus.ERROR,
                    error=f"OpenCode refused redirect (HTTP {r.status_code})",
                )
            if r.status_code == 401:
                return UsageSnapshot(
                    provider=self.id,
                    display_name=self.display_name,
                    status=SnapshotStatus.AUTH_REQUIRED,
                    error="OpenCode rejected the API key",
                )
            if r.status_code == 403:
                return UsageSnapshot(
                    provider=self.id,
                    display_name=self.display_name,
                    status=SnapshotStatus.ERROR,
                    error="No active OpenCode Go subscription on this key",
                )
            r.raise_for_status()
            payload = r.json()
            if not isinstance(payload, dict):
                raise ValueError("Unexpected OpenCode response")
            return build_opencode_snapshot(payload)
        except requests.RequestException as exc:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=f"OpenCode request failed: {exc}",
            )
        except ValueError as exc:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=str(exc),
            )
