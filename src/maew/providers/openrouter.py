"""OpenRouter usage & credit provider via official OpenRouter REST API."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

import requests

from ..models import SnapshotStatus, UsageMetric, UsageSnapshot
from .base import Provider

OPENROUTER_API = "https://openrouter.ai/api/v1"


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _next_local_midnight() -> datetime:
    tomorrow = (datetime.now() + timedelta(days=1)).date()
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day)


def _as_float(val: object) -> float | None:
    if isinstance(val, bool) or val is None:
        return None
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def build_openrouter_snapshot(
    key_info: dict[str, Any],
    *,
    credits: dict[str, Any] | None = None,
    daily_budget: float | None = None,
) -> UsageSnapshot:
    daily = _as_float(key_info.get("usage_daily")) or 0.0
    monthly = _as_float(key_info.get("usage_monthly")) or 0.0
    key_limit = _as_float(key_info.get("limit"))
    key_remaining = _as_float(key_info.get("limit_remaining"))

    metrics: list[UsageMetric] = []

    # 1. Daily budget gauge (or key credit limit gauge)
    if daily_budget and daily_budget > 0:
        pct = max(0.0, min(100.0, (daily / daily_budget) * 100.0))
        metrics.append(
            UsageMetric(
                label="24h",
                percent_used=pct,
                resets_at=_next_local_midnight(),
                note=f"${daily:.2f} / ${daily_budget:.2f}",
                window_hours=24.0,
                group="OpenRouter",
            )
        )
    elif key_limit and key_limit > 0 and key_remaining is not None:
        used = max(0.0, key_limit - key_remaining)
        pct = max(0.0, min(100.0, (used / key_limit) * 100.0))
        metrics.append(
            UsageMetric(
                label="Limit",
                percent_used=pct,
                reset_label=f"${key_remaining:.2f} left",
                note=f"${used:.2f} / ${key_limit:.2f}",
                group="OpenRouter",
            )
        )

    # 2. Account credits (when key has credits access)
    if isinstance(credits, dict):
        total = _as_float(credits.get("total_credits"))
        used = _as_float(credits.get("total_usage"))
        if total is not None and total > 0 and used is not None:
            left = max(0.0, total - used)
            pct = max(0.0, min(100.0, (used / total) * 100.0))
            metrics.append(
                UsageMetric(
                    label="Credits",
                    percent_used=pct,
                    reset_label=f"${left:.2f} left",
                    note=f"Today ${daily:.2f} · Month ${monthly:.2f}",
                    group="OpenRouter",
                )
            )

    if not metrics:
        metrics.append(
            UsageMetric(
                label="24h",
                percent_used=0.0,
                reset_label=f"${daily:.2f} today",
                note=f"Month ${monthly:.2f} (set daily budget in Settings for % bar)",
                window_hours=24.0,
                group="OpenRouter",
            )
        )

    return UsageSnapshot(
        provider="openrouter",
        display_name="OpenRouter",
        status=SnapshotStatus.OK,
        metrics=metrics,
        extra={"daily_usd": daily, "monthly_usd": monthly},
    )


class OpenRouterProvider(Provider):
    id = "openrouter"
    display_name = "OpenRouter"
    short_label = "OR"
    kind = "api_key"

    def __init__(
        self,
        *,
        key_loader: Callable[[], str | None],
        daily_budget: float | None = None,
    ) -> None:
        self._key_loader = key_loader
        self.daily_budget = daily_budget

    def fetch(self) -> UsageSnapshot:
        api_key = self._key_loader()
        if not api_key:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.AUTH_REQUIRED,
                error="Add an OpenRouter API key in Settings",
            )

        try:
            r_key = requests.get(
                f"{OPENROUTER_API}/key",
                headers=_headers(api_key),
                timeout=15,
                allow_redirects=False,
            )
            if 300 <= r_key.status_code < 400:
                return UsageSnapshot(
                    provider=self.id,
                    display_name=self.display_name,
                    status=SnapshotStatus.ERROR,
                    error=f"OpenRouter refused redirect (HTTP {r_key.status_code})",
                )
            if r_key.status_code in (401, 403):
                return UsageSnapshot(
                    provider=self.id,
                    display_name=self.display_name,
                    status=SnapshotStatus.AUTH_REQUIRED,
                    error="OpenRouter rejected the API key",
                )
            r_key.raise_for_status()
            payload = r_key.json()
            key_info = payload.get("data", payload) if isinstance(payload, dict) else {}

            credits = None
            try:
                r_cred = requests.get(
                    f"{OPENROUTER_API}/credits",
                    headers=_headers(api_key),
                    timeout=10,
                    allow_redirects=False,
                )
                if r_cred.status_code == 200:
                    c_payload = r_cred.json()
                    if isinstance(c_payload, dict) and isinstance(c_payload.get("data"), dict):
                        credits = c_payload["data"]
            except requests.RequestException:
                pass

            return build_openrouter_snapshot(
                key_info if isinstance(key_info, dict) else {},
                credits=credits,
                daily_budget=self.daily_budget,
            )
        except requests.RequestException as exc:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=f"OpenRouter request failed: {exc}",
            )
        except ValueError as exc:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=str(exc),
            )
