"""Claude.ai web usage provider (5-hour session & weekly limits).

Uses an isolated Edge WebView2 profile (%APPDATA%/maew-ai-check/webview2) —
NEVER touches the user's main Edge/Chrome browser profile and NEVER sends
cookies outside claude.ai.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Callable
from urllib.parse import urlparse

from ..models import SnapshotStatus, UsageMetric, UsageSnapshot
from .base import Provider

log = logging.getLogger("maew.providers.claude_web")

CLAUDE_LOGIN_URL = "https://claude.ai/login"
CLAUDE_USAGE_URL = "https://claude.ai/settings/usage"

_WEEKDAYS = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}

_SECURITY_MARKERS = (
    "verify you are human",
    "verifying you are human",
    "security verification",
    "checking if the site connection is secure",
    "performance & security by cloudflare",
)

# Injected into https://claude.ai/settings/usage inside an isolated hidden WebView2 window.
EXTRACTOR_JS = r"""
(() => {
  const ROW_LABEL_GROUPS = [
    ['Current session'],
    ['All models', 'This week'],
    ['Fable this week', 'Fable'],
    ['Daily included routine runs']
  ];

  function norm(el) {
    return (el.textContent || '').replace(/\s+/g, ' ').trim();
  }

  function withoutVersion(after) {
    return after.replace(/^\d+(?:\.\d+)?\s+/, '');
  }

  function isIdleRowTail(after) {
    const tail = withoutVersion(after);
    return /^resets?\s+when\b/i.test(tail) ||
      /^starts\s+when\b.*\bmessage\b/i.test(tail) ||
      /^starts\s+with\b.*\b(?:first\s+)?message\b/i.test(tail) ||
      /^you\s+haven['’]t\s+used\b.*\byet\b/i.test(tail);
  }

  function hasUsageValue(after) {
    return /\d+(?:\.\d+)?\s*%(?:\s*(?:used|remaining))?/i.test(after) ||
      /\b(?:used|remaining)\s*:?\s*\d+(?:\.\d+)?\s*%/i.test(after);
  }

  function hasUsageReading(after) {
    return /\d+(?:\.\d+)?\s*%\s*(?:used|remaining)/i.test(after) ||
      /\b(?:used|remaining)\s*:?\s*\d+(?:\.\d+)?\s*%/i.test(after);
  }

  function labelTailMatches(text, label, predicate) {
    const lower = text.toLowerCase();
    const needle = label.toLowerCase();
    let i = lower.indexOf(needle);
    while (i !== -1) {
      const after = text.slice(i + needle.length).trim();
      if (predicate(after)) return true;
      i = lower.indexOf(needle, i + 1);
    }
    return false;
  }

  function headsARow(text, label) {
    const needsReading = label.toLowerCase() === 'fable';
    return labelTailMatches(text, label, (after) => {
      const tail = withoutVersion(after);
      return isIdleRowTail(after) ||
        (needsReading ? hasUsageReading(tail) : hasUsageValue(tail));
    });
  }

  function isEmbeddedLabel(text, index, label) {
    return label.toLowerCase() === 'this week' &&
      text.slice(Math.max(0, index - 6), index).toLowerCase() === 'fable ';
  }

  function nextRowLabel(text, start) {
    const lower = text.toLowerCase();
    let end = text.length;
    for (const group of ROW_LABEL_GROUPS) {
      for (const label of group) {
        let index = lower.indexOf(label.toLowerCase(), start);
        while (index !== -1 && isEmbeddedLabel(text, index, label)) {
          index = lower.indexOf(label.toLowerCase(), index + 1);
        }
        if (index !== -1 && index < end) end = index;
      }
    }
    return end;
  }

  function rowText(text, labels) {
    const lower = text.toLowerCase();
    let best = null;
    for (const label of labels) {
      let index = lower.indexOf(label.toLowerCase());
      while (index !== -1) {
        if (!isEmbeddedLabel(text, index, label)) {
          const afterLabel = index + label.length;
          const candidate = text.slice(index, nextRowLabel(text, afterLabel)).trim();
          if (headsARow(candidate, label) && (!best || candidate.length < best.length)) {
            best = candidate;
          }
        }
        index = lower.indexOf(label.toLowerCase(), index + 1);
      }
    }
    return best;
  }

  function findRowByLabels(labels) {
    const candidates = Array.from(document.querySelectorAll('div, section, li'));
    let best = null;
    let bestScore = Infinity;
    for (const el of candidates) {
      const t = norm(el);
      const row = rowText(t, labels);
      if (!row) continue;
      let score = row.length;
      const rect = el.getBoundingClientRect();
      if (rect.height > 140) score += 5000;
      if (score < bestScore) {
        best = row;
        bestScore = score;
      }
    }
    return best;
  }

  function readRow(labels) {
    const text = findRowByLabels(labels);
    if (!text) return null;
    const pctMatches = Array.from(text.matchAll(/(\d+(?:\.\d+)?)\s*%/g));
    const pctMatch = pctMatches[pctMatches.length - 1];
    const idle = labels.some(label => labelTailMatches(text, label, isIdleRowTail));
    const remaining = /remaining/i.test(text);
    const used = /used/i.test(text);
    const resetMatch = text.match(/Resets?\s+(?:in\s+)?(.+?)(?=\s*$|\s+(?:Daily|Weekly|All|Current|Claude|Fable|You)\b|\s*\d+%)/i);
    const pausedMatch = text.match(/\b((?:paused|unavailable|blocked)\b.+?\b(?:resets?|renews?))(?=\s*\d+%|\s*$)/i);
    return {
      raw: text.slice(0, 300),
      percent: idle ? 0 : (pctMatch ? parseFloat(pctMatch[1]) : null),
      kind: idle ? 'used' : (remaining ? 'remaining' : (used ? 'used' : 'unknown')),
      reset_text: pausedMatch ? pausedMatch[1].trim() : (resetMatch ? resetMatch[1].trim() : null),
    };
  }

  function onUsageRoute() {
    return /\/settings\/usage/.test(location.pathname) ||
      /settings\/usage/i.test(location.hash);
  }

  const bodyText = (document.body && document.body.textContent || '').replace(/\s+/g, ' ').trim();
  const isLoggedOut =
    (location.hostname === 'claude.ai' &&
      (/^\/(?:login|logout)(?:\/|$)/.test(location.pathname) ||
        /^Sign in\s*[-–—]\s*Claude$/i.test(document.title))) ||
    (!!document.querySelector('a[href*="/login"]') &&
      !/Plan usage limits|Your usage/i.test(bodyText));

  const session = readRow(ROW_LABEL_GROUPS[0]);
  const weeklyAll = readRow(ROW_LABEL_GROUPS[1]);
  const weeklyFable = readRow(ROW_LABEL_GROUPS[2]);

  const usagePageVisible = !!document.querySelector('[data-usage-bars="usage_page"]') ||
    /Your usage/i.test(bodyText);
  const emptySession = !session && !!weeklyAll && weeklyAll.percent === 0 &&
    weeklyAll.kind === 'used' && onUsageRoute() && usagePageVisible &&
    /No usage yet\.\s*100%\s+of your weekly limit is available/i.test(bodyText);
  const sessionResult = session || (emptySession ? {
    raw: 'No usage yet', percent: 0, kind: 'used', reset_text: null
  } : null);

  const usagePanelSignals = /Plan usage limits|Your usage|Current session|All models|This week/i.test(bodyText);
  const idleUsagePanel = /Plan usage limits|Your usage/i.test(bodyText) &&
    /Current session/i.test(bodyText) &&
    /All models|This week/i.test(bodyText) &&
    !/%/.test(bodyText);
  const requiredRowsReady = !!sessionResult && !!weeklyAll;

  if (!isLoggedOut && (onUsageRoute() || usagePanelSignals) && !requiredRowsReady && !idleUsagePanel) {
    return {
      __retry: true,
      url: location.href,
      title: document.title,
      body_text: bodyText.slice(0, 2000),
    };
  }

  return {
    logged_out: isLoggedOut,
    session: sessionResult,
    weekly_all: weeklyAll,
    weekly_fable: weeklyFable,
    url: location.href,
    title: document.title,
    body_text: bodyText.slice(0, 2000),
  };
})()
"""


def parse_reset_text(text: str | None, now: datetime | None = None) -> datetime | None:
    if not text:
        return None
    now = now or datetime.now()
    cleaned = text.strip().rstrip(".")
    cleaned = re.sub(r"^at\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+at\s+", " ", cleaned, count=1, flags=re.IGNORECASE)

    rel = re.fullmatch(
        r"(?:in\s+)?(?:(\d+)\s*(?:days?|d))?\s*"
        r"(?:(\d+)\s*(?:hours?|hrs?|h))?\s*"
        r"(?:(\d+)\s*(?:minutes?|mins?|m))?\s*"
        r"(?:(\d+)\s*(?:seconds?|secs?|s))?",
        cleaned,
        re.IGNORECASE,
    )
    if rel and any(g is not None for g in rel.groups()):
        days, hours, minutes, seconds = (int(g or 0) for g in rel.groups())
        return now + timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)

    for fmt in ("%b %d, %Y %I:%M %p", "%b %d %I:%M %p", "%B %d, %Y %I:%M %p"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue

    weekday_match = re.match(r"([A-Za-z]+)\s+(.+)$", cleaned)
    if weekday_match:
        weekday = _WEEKDAYS.get(weekday_match.group(1).lower())
        time_text = weekday_match.group(2).strip()
        if weekday is not None:
            for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
                try:
                    t = datetime.strptime(time_text, fmt).time()
                    days_ahead = (weekday - now.weekday()) % 7
                    candidate = datetime.combine(now.date() + timedelta(days=days_ahead), t)
                    if candidate <= now:
                        candidate += timedelta(days=7)
                    return candidate
                except ValueError:
                    continue

    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
        try:
            t = datetime.strptime(cleaned, fmt).time()
            candidate = datetime.combine(now.date(), t)
            if candidate < now:
                candidate += timedelta(days=1)
            return candidate
        except ValueError:
            continue

    return None


def _normalize_percent(percent: Any, kind: str) -> float | None:
    if isinstance(percent, bool) or not isinstance(percent, (int, float)):
        return None
    val = float(percent)
    if kind == "remaining":
        val = 100.0 - val
    return max(0.0, min(100.0, val))


def build_claude_web_snapshot(payload: dict[str, Any]) -> UsageSnapshot:
    url = str(payload.get("url") or "").lower()
    title = str(payload.get("title") or "").lower()
    body = str(payload.get("body_text") or "").lower()
    combined = f"{title} {body}"

    if payload.get("logged_out") or "/login" in url or "/logout" in url:
        return UsageSnapshot(
            provider="claude_web",
            display_name="Claude.ai",
            status=SnapshotStatus.AUTH_REQUIRED,
            error="Not signed in — click Connect to sign in via isolated WebView2",
        )

    if any(marker in combined for marker in _SECURITY_MARKERS) or (
        "just a moment" in title and "cloudflare" in combined
    ):
        return UsageSnapshot(
            provider="claude_web",
            display_name="Claude.ai",
            status=SnapshotStatus.AUTH_REQUIRED,
            error="Cloudflare check needed — click Connect to verify",
        )

    row_defs = (
        ("session", "5h", 5.0),
        ("weekly_all", "7d", 168.0),
        ("weekly_fable", "Fable", 168.0),
    )
    metrics: list[UsageMetric] = []
    for key, label, hours in row_defs:
        card = payload.get(key)
        if not isinstance(card, dict):
            continue
        pct = _normalize_percent(card.get("percent"), str(card.get("kind") or ""))
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
                group="Claude",
            )
        )

    if not metrics:
        parsed_url = urlparse(url)
        if (
            parsed_url.netloc == "claude.ai"
            and ("plan usage limits" in body or "your usage" in body)
            and "%" not in body
        ):
            metrics = [
                UsageMetric("5h", 0.0, None, "idle", window_hours=5.0, group="Claude"),
                UsageMetric("7d", 0.0, None, "idle", window_hours=168.0, group="Claude"),
            ]
        else:
            return UsageSnapshot(
                provider="claude_web",
                display_name="Claude.ai",
                status=SnapshotStatus.ERROR,
                error="Could not read usage rows (layout may have changed or session expired)",
            )

    return UsageSnapshot(
        provider="claude_web",
        display_name="Claude.ai",
        status=SnapshotStatus.OK,
        metrics=metrics,
    )


class ClaudeWebProvider(Provider):
    id = "claude_web"
    display_name = "Claude.ai"
    short_label = "CL"
    kind = "web"

    def __init__(self, scraper_fn: Callable[[str, str], dict[str, Any] | None]) -> None:
        self._scraper_fn = scraper_fn

    def fetch(self) -> UsageSnapshot:
        try:
            payload = self._scraper_fn(CLAUDE_USAGE_URL, EXTRACTOR_JS)
        except Exception as exc:  # noqa: BLE001
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=f"Claude scrape failed: {exc}",
            )
        if not isinstance(payload, dict):
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.AUTH_REQUIRED,
                error="Connect Claude.ai to see 5h / Weekly %",
            )
        return build_claude_web_snapshot(payload)
