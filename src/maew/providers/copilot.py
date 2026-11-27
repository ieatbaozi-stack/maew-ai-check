"""GitHub Copilot billing usage provider via official GitHub REST API.

Uses a fine-grained GitHub PAT stored encrypted in Windows DPAPI (SecretStore).
Supports both newer AI Credits billing summary and legacy Premium Requests endpoints.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable

import requests

from ..models import SnapshotStatus, UsageMetric, UsageSnapshot
from .base import Provider

log = logging.getLogger("maew.providers.copilot")

GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2026-03-10"
_GH_SLUG_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


def _headers(pat: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }


def _norm(val: object) -> str:
    return str(val or "").strip().lower().replace(" ", "_").replace("-", "_")


def _is_credit_item(item: dict[str, Any]) -> bool:
    sku = _norm(item.get("sku"))
    unit = _norm(item.get("unitType") or item.get("unit_type"))
    product = _norm(item.get("product"))
    return (
        sku in ("copilot_ai_credits", "copilot_ai_unit")
        or "ai_credit" in sku
        or "ai_unit" in sku
        or "ai_credit" in unit
        or "ai_unit" in unit
        or (product == "copilot" and ("credit" in unit or "unit" in unit))
    )


def _is_legacy_item(item: dict[str, Any]) -> bool:
    sku = _norm(item.get("sku"))
    unit = _norm(item.get("unitType") or item.get("unit_type"))
    return "premium_request" in sku or "premium_request" in unit


def _qty(item: dict[str, Any]) -> float:
    for key in ("grossQuantity", "quantity", "discountQuantity", "netQuantity"):
        val = item.get(key)
        if val is not None:
            return float(val or 0)
    amount = item.get("grossAmount")
    if amount is not None:
        return float(amount or 0) * 100.0
    return 0.0


def _next_month_local(now_utc: datetime | None = None) -> datetime:
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.month == 12:
        nxt = datetime(now_utc.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(now_utc.year, now_utc.month + 1, 1, tzinfo=timezone.utc)
    return nxt.astimezone().replace(tzinfo=None)


def build_copilot_snapshot(payload: dict[str, Any], monthly_quota: int = 1500) -> UsageSnapshot:
    raw_items = payload.get("usageItems")
    items = [it for it in (raw_items if isinstance(raw_items, list) else []) if isinstance(it, dict)]

    credit_items = [it for it in items if _is_credit_item(it)]
    legacy_items = [it for it in items if _is_legacy_item(it)]
    selected = credit_items if credit_items else (legacy_items or items)
    used = sum(_qty(it) for it in selected)

    quota = max(1, int(monthly_quota or 1500))
    pct = max(0.0, min(100.0, (used / quota) * 100.0))
    used_fmt = f"{used:.1f}" if used % 1 else f"{int(used)}"

    metric = UsageMetric(
        label="30d",
        percent_used=pct,
        resets_at=_next_month_local(),
        note=f"{used_fmt}/{quota} credits",
        window_hours=720.0,
        group="Copilot",
    )
    return UsageSnapshot(
        provider="copilot",
        display_name="Copilot",
        status=SnapshotStatus.OK,
        metrics=[metric],
        extra={"used": used, "quota": quota},
    )


class CopilotProvider(Provider):
    id = "copilot"
    display_name = "Copilot"
    short_label = "CP"
    kind = "api_key"

    def __init__(
        self,
        *,
        key_loader: Callable[[], str | None],
        username: str | None = None,
        billing_org: str | None = None,
        monthly_quota: int = 1500,
    ) -> None:
        self._key_loader = key_loader
        self.username = username
        self.billing_org = billing_org
        self.monthly_quota = monthly_quota

    def _resolve_username(self, pat: str) -> str | None:
        if self.username:
            return self.username if _GH_SLUG_RE.match(self.username) else None
        r = requests.get(
            f"{GITHUB_API}/user",
            headers=_headers(pat),
            timeout=10,
            allow_redirects=False,
        )
        if r.status_code == 200:
            data = r.json()
            login = data.get("login") if isinstance(data, dict) else None
            if isinstance(login, str) and _GH_SLUG_RE.match(login):
                return login
        return None

    def fetch(self) -> UsageSnapshot:
        pat = self._key_loader()
        if not pat:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.AUTH_REQUIRED,
                error="Add a GitHub PAT (Plan: read) in Settings",
            )

        now = datetime.now(timezone.utc)
        params: dict[str, Any] = {"year": now.year, "month": now.month, "product": "copilot"}
        try:
            if self.billing_org:
                if not _GH_SLUG_RE.match(self.billing_org):
                    return UsageSnapshot(
                        provider=self.id,
                        display_name=self.display_name,
                        status=SnapshotStatus.ERROR,
                        error="Invalid GitHub organization name in config",
                    )
                url = f"{GITHUB_API}/organizations/{self.billing_org}/settings/billing/usage/summary"
                r = requests.get(
                    url, params=params, headers=_headers(pat), timeout=15, allow_redirects=False
                )
            else:
                user = self._resolve_username(pat)
                if not user:
                    return UsageSnapshot(
                        provider=self.id,
                        display_name=self.display_name,
                        status=SnapshotStatus.AUTH_REQUIRED,
                        error="Could not resolve GitHub username (check PAT or set username)",
                    )
                url = f"{GITHUB_API}/users/{user}/settings/billing/usage/summary"
                r = requests.get(
                    url, params=params, headers=_headers(pat), timeout=15, allow_redirects=False
                )
                if r.status_code in (404, 422):
                    legacy_url = f"{GITHUB_API}/users/{user}/settings/billing/premium_request/usage"
                    r = requests.get(
                        legacy_url,
                        params={"year": now.year, "month": now.month},
                        headers=_headers(pat),
                        timeout=15,
                        allow_redirects=False,
                    )

            if 300 <= r.status_code < 400:
                return UsageSnapshot(
                    provider=self.id,
                    display_name=self.display_name,
                    status=SnapshotStatus.ERROR,
                    error=f"GitHub API refused redirect (HTTP {r.status_code})",
                )
            if r.status_code in (401, 403):
                return UsageSnapshot(
                    provider=self.id,
                    display_name=self.display_name,
                    status=SnapshotStatus.AUTH_REQUIRED,
                    error=f"GitHub rejected PAT (HTTP {r.status_code})",
                )
            r.raise_for_status()
            payload = r.json()
            if not isinstance(payload, dict):
                raise ValueError("Unexpected GitHub billing response")
            return build_copilot_snapshot(payload, monthly_quota=self.monthly_quota)
        except requests.RequestException as exc:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=f"GitHub API request failed: {exc}",
            )
        except ValueError as exc:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=str(exc),
            )
