from __future__ import annotations

from datetime import datetime

from maew.models import SnapshotStatus
from maew.providers.claude_web import build_claude_web_snapshot, parse_reset_text


def test_build_claude_web_snapshot_normal():
    payload = {
        "logged_out": False,
        "url": "https://claude.ai/settings/usage",
        "title": "Settings - Claude",
        "body_text": "Plan usage limits Current session 42% used All models 18% used",
        "session": {"percent": 42, "kind": "used", "reset_text": "2 hr 30 min"},
        "weekly_all": {"percent": 18, "kind": "used", "reset_text": "Mon 6:00 PM"},
        "weekly_fable": None,
    }
    snap = build_claude_web_snapshot(payload)
    assert snap.status == SnapshotStatus.OK
    assert [m.label for m in snap.metrics] == ["5h", "7d"]
    assert snap.metrics[0].percent_used == 42.0
    assert snap.metrics[1].percent_used == 18.0
    assert snap.metrics[0].resets_at is not None


def test_build_claude_web_snapshot_logged_out():
    snap = build_claude_web_snapshot({"logged_out": True, "url": "https://claude.ai/login"})
    assert snap.status == SnapshotStatus.AUTH_REQUIRED


def test_build_claude_web_snapshot_cloudflare():
    snap = build_claude_web_snapshot(
        {
            "logged_out": False,
            "url": "https://claude.ai/settings/usage",
            "title": "Just a moment...",
            "body_text": "Performance & security by Cloudflare",
        }
    )
    assert snap.status == SnapshotStatus.AUTH_REQUIRED


def test_parse_reset_text_relative():
    now = datetime(2026, 11, 27, 12, 0, 0)
    dt = parse_reset_text("2 hr 15 min", now=now)
    assert dt == datetime(2026, 11, 27, 14, 15, 0)
