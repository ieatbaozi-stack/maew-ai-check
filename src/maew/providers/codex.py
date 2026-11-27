"""OpenAI Codex (ChatGPT) web usage provider (5h / 7d plan limits).

Uses the same isolated Edge WebView2 profile (%APPDATA%/maew-ai-check/webview2)
and standardized 5h / 7d metric labels as Claude.ai.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Callable

from ..models import SnapshotStatus, UsageMetric, UsageSnapshot
from .base import Provider
from .claude_web import parse_reset_text

log = logging.getLogger("maew.providers.codex")

CODEX_LOGIN_URL = "https://chatgpt.com/auth/login"
CODEX_USAGE_URL = "https://chatgpt.com/settings/usage?tab=overview"

_SECURITY_MARKERS = (
    "verify you are human",
    "verifying you are human",
    "security verification",
    "checking if the site connection is secure",
    "performance & security by cloudflare",
)

EXTRACTOR_JS = r"""
(() => {
  function visibleText(el) {
    return ((el && (el.innerText || el.textContent)) || '').replace(/\s+/g, ' ').trim();
  }

  function windowTextAfterLabel(label, nextLabels) {
    const lowerText = limitsText.toLowerCase();
    const start = lowerText.indexOf(label.toLowerCase());
    if (start < 0) return '';
    let end = limitsText.length;
    for (const nextLabel of nextLabels) {
      const candidate = lowerText.indexOf(nextLabel.toLowerCase(), start + label.length);
      if (candidate >= 0 && candidate < end) end = candidate;
    }
    return limitsText.slice(start, end).trim();
  }

  function maybeSelectOverviewTab() {
    if (/Weekly limit/i.test(limitsText) && /\d+(?:\.\d+)?\s*%\s*left\b/i.test(limitsText)) {
      return null;
    }
    const labels = Array.from(document.querySelectorAll('button,a,[role="tab"],[role="button"]'));
    const label = labels.find(el => visibleText(el).toLowerCase() === 'overview');
    if (!label) return null;
    const target = label.closest('button,a,[role="tab"],[role="button"]') || label;
    const selected =
      target.getAttribute('aria-pressed') === 'true' ||
      target.getAttribute('aria-selected') === 'true' ||
      target.getAttribute('data-state') === 'active';
    if (selected) return 'waiting for plan limits';
    target.click();
    return 'selected overview tab';
  }

  function readCard(label, nextLabels) {
    const text = windowTextAfterLabel(label, nextLabels);
    if (!text) return null;
    const pctMatch = text.match(/(\d+(?:\.\d+)?)\s*%\s*left\b/i);
    if (!pctMatch) return null;
    const resetMatch = text.match(/Resets?\s+(?:(?:at|on|in)\s+)?(.+?)(?=\s*$|\s+\d+(?:\.\d+)?\s*%)/i);
    return {
      raw: text.slice(0, 300),
      percent: parseFloat(pctMatch[1]),
      kind: 'remaining',
      reset_text: resetMatch ? resetMatch[1].trim() : null,
    };
  }

  function numericAttribute(el, name) {
    const raw = el.getAttribute(name);
    if (raw === null || String(raw).trim() === '') return null;
    const number = Number(raw);
    return Number.isFinite(number) ? number : null;
  }

  function remainingBarValues() {
    const values = Array.from(document.querySelectorAll('progress'))
      .filter(el => numericAttribute(el, 'max') === 100)
      .map(el => numericAttribute(el, 'value'));
    return values.every(v => v !== null && v >= 0 && v <= 100) ? values : [];
  }

  const bodyText = visibleText(document.body);
  const limitsText = bodyText.split(/\bPlan limits\b/i).pop()
    .split(/\bCredits\b|\bUsage limit resets\b|\bCredit usage history\b/i)[0];

  const overviewReason = maybeSelectOverviewTab();
  if (overviewReason) {
    return { __retry: true, url: location.href, title: document.title, body_text: bodyText.slice(0, 2000) };
  }

  const lowerText = bodyText.toLowerCase();
  const isLoggedOut =
    !!document.querySelector('a[href*="/auth/login"], a[href*="/login"]') ||
    location.pathname.includes('/auth/login') ||
    location.pathname === '/login' ||
    document.title.toLowerCase().includes('login') ||
    (/log in|sign in/.test(lowerText) && !/Plan limits/i.test(bodyText));

  let session = readCard('5-hour limit', ['Weekly limit']);
  let weekly = readCard('Weekly limit', ['5-hour limit']);

  if (!session && !weekly && !isLoggedOut) {
    const bars = remainingBarValues();
    if (bars.length === 2) {
      session = { percent: bars[0], kind: 'remaining', reset_text: null };
      weekly = { percent: bars[1], kind: 'remaining', reset_text: null };
    } else if (bars.length === 1) {
      weekly = { percent: bars[0], kind: 'remaining', reset_text: null };
    }
  }

  if (!isLoggedOut && !session && !weekly && /settings\/usage/i.test(location.pathname)) {
    return { __retry: true, url: location.href, title: document.title, body_text: bodyText.slice(0, 2000) };
  }

  return {
    logged_out: isLoggedOut,
    session,
    weekly,
    url: location.href,
    title: document.title,
    body_text: bodyText.slice(0, 2000),
  };
})()
"""


def _normalize_percent(percent: Any, kind: str) -> float | None:
    if isinstance(percent, bool) or not isinstance(percent, (int, float)):
        return None
    val = float(percent)
    if kind == "remaining":
        val = 100.0 - val
    return max(0.0, min(100.0, val))


def build_codex_snapshot(payload: dict[str, Any]) -> UsageSnapshot:
    url = str(payload.get("url") or "").lower()
    title = str(payload.get("title") or "").lower()
    body = str(payload.get("body_text") or "").lower()
    combined = f"{title} {body}"

    if payload.get("logged_out") or "/auth/login" in url or "/login" in url or "/logout" in url:
        return UsageSnapshot(
            provider="codex",
            display_name="Codex",
            status=SnapshotStatus.AUTH_REQUIRED,
            error="Sign in to ChatGPT to view 5h / 7d gauges",
        )

    if any(m in combined for m in _SECURITY_MARKERS) or ("just a moment" in title and "cloudflare" in combined):
        return UsageSnapshot(
            provider="codex",
            display_name="Codex",
            status=SnapshotStatus.AUTH_REQUIRED,
            error="Security verification needed — click Connect",
        )

    metrics: list[UsageMetric] = []
    for key, label, hours in (("session", "5h", 5.0), ("weekly", "7d", 168.0)):
        card = payload.get(key)
        if not isinstance(card, dict):
            continue
        pct = _normalize_percent(card.get("percent"), str(card.get("kind") or "remaining"))
        if pct is None:
            continue
        reset_text = card.get("reset_text")
        resets_at = parse_reset_text(reset_text if isinstance(reset_text, str) else None)
        reset_label = "idle" if pct == 0.0 and resets_at is None else None
        metrics.append(
            UsageMetric(
                label=label,
                percent_used=pct,
                resets_at=resets_at,
                reset_label=reset_label,
                note=reset_text if isinstance(reset_text, str) else None,
                window_hours=hours,
                group="Codex",
            )
        )

    if not metrics:
        return UsageSnapshot(
            provider="codex",
            display_name="Codex",
            status=SnapshotStatus.ERROR,
            error="Could not read Codex usage (layout may have changed)",
        )

    return UsageSnapshot(
        provider="codex",
        display_name="Codex",
        status=SnapshotStatus.OK,
        metrics=metrics,
    )


class CodexProvider(Provider):
    id = "codex"
    display_name = "Codex"
    short_label = "CX"
    kind = "web"

    def __init__(self, scraper_fn: Callable[[str, str], dict[str, Any] | None]) -> None:
        self._scraper_fn = scraper_fn

    def fetch(self) -> UsageSnapshot:
        cache_buster = int(datetime.now().timestamp())
        try:
            payload = self._scraper_fn(f"{CODEX_USAGE_URL}&maew_ts={cache_buster}", EXTRACTOR_JS)
        except Exception as exc:  # noqa: BLE001
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=f"Codex scrape failed: {exc}",
            )
        if not isinstance(payload, dict):
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.AUTH_REQUIRED,
                error="Sign in to ChatGPT to view 5h / 7d gauges",
            )
        return build_codex_snapshot(payload)
