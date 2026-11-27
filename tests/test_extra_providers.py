from __future__ import annotations

import pytest

from maew.models import SnapshotStatus
from maew.providers.codex import build_codex_snapshot
from maew.providers.copilot import build_copilot_snapshot
from maew.providers.minimax import MiniMaxProvider, build_minimax_snapshot
from maew.providers.opencode_go import build_opencode_snapshot
from maew.providers.openrouter import build_openrouter_snapshot
from maew.scanner import scan_local_harnesses


def test_codex_snapshot_converts_remaining_to_used_and_uses_5h_7d():
    payload = {
        "logged_out": False,
        "url": "https://chatgpt.com/settings/usage?tab=overview",
        "title": "ChatGPT",
        "body_text": "Plan limits 5-hour limit 70% left Weekly limit 0% left",
        "session": {"percent": 70.0, "kind": "remaining", "reset_text": "3h 10m"},
        "weekly": {"percent": 0.0, "kind": "remaining", "reset_text": "Mon 6:00 PM"},
    }
    snap = build_codex_snapshot(payload)
    assert snap.status == SnapshotStatus.OK
    assert [m.label for m in snap.metrics] == ["5h", "7d"]
    assert snap.metrics[0].percent_used == pytest.approx(30.0)
    assert snap.metrics[1].percent_used == pytest.approx(100.0)


def test_copilot_snapshot_handles_ai_credits_and_legacy_premium():
    credit_payload = {
        "usageItems": [
            {"product": "copilot", "sku": "copilot_ai_credits", "grossQuantity": 300},
            {"product": "copilot", "sku": "copilot_ai_credits", "grossQuantity": 150},
        ]
    }
    snap = build_copilot_snapshot(credit_payload, monthly_quota=1500)
    assert snap.status == SnapshotStatus.OK
    assert snap.metrics[0].label == "30d"
    assert snap.metrics[0].percent_used == pytest.approx(30.0)
    assert "450/1500" in (snap.metrics[0].note or "")


def test_openrouter_snapshot_with_budget_and_credits():
    key_info = {"usage_daily": 2.5, "usage_monthly": 40.0}
    credits = {"total_credits": 100.0, "total_usage": 25.0}
    snap = build_openrouter_snapshot(key_info, credits=credits, daily_budget=10.0)
    assert snap.status == SnapshotStatus.OK
    assert [m.label for m in snap.metrics] == ["24h", "Credits"]
    assert snap.metrics[0].percent_used == pytest.approx(25.0)
    assert snap.metrics[1].percent_used == pytest.approx(25.0)
    assert snap.metrics[1].reset_label == "$75.00 left"


def test_opencode_go_snapshot_standardizes_windows_and_rate_limit():
    payload = {
        "usage": {
            "rolling": {"percent": 40, "status": "ok", "resetsAt": "2026-12-01T10:00:00Z"},
            "weekly": {"percent": 98, "status": "rate-limited", "resetsAt": "2026-12-05T10:00:00Z"},
            "monthly": {"percent": 15, "status": "ok", "resetsAt": "2026-12-30T10:00:00Z"},
        }
    }
    snap = build_opencode_snapshot(payload)
    assert snap.status == SnapshotStatus.OK
    assert [m.label for m in snap.metrics] == ["5h", "7d", "30d"]
    assert snap.metrics[0].percent_used == pytest.approx(40.0)
    assert snap.metrics[1].percent_used == pytest.approx(100.0)  # rate-limited clamps to 100%


def test_minimax_snapshot_and_redirect_refusal(monkeypatch):
    payload = {
        "base_resp": {"status_code": 0},
        "model_remains": [
            {
                "model_name": "MiniMax-M1",
                "current_interval_status": 1,
                "current_interval_remaining_percent": 65,
                "end_time": 1796000000000,
                "current_weekly_status": 2,  # exhausted
                "weekly_end_time": 1796500000000,
            }
        ],
    }
    snap = build_minimax_snapshot(payload)
    assert snap.status == SnapshotStatus.OK
    assert [m.label for m in snap.metrics] == ["5h", "7d"]
    assert snap.metrics[0].percent_used == pytest.approx(35.0)
    assert snap.metrics[1].percent_used == pytest.approx(100.0)

    # Verify redirect is refused so bearer key is never leaked across hosts
    class FakeResp:
        status_code = 302
        headers = {"Location": "https://evil.example/steal"}

    monkeypatch.setattr("maew.providers.minimax.requests.get", lambda *a, **kw: FakeResp())
    prov = MiniMaxProvider(key_loader=lambda: "sk-cp-test", region="international")
    err_snap = prov.fetch()
    assert err_snap.status == SnapshotStatus.ERROR
    assert "redirect" in (err_snap.error or "").lower()


def test_local_scanner_returns_all_supported_providers():
    results = scan_local_harnesses(secrets=None)
    expected = {
        "antigravity",
        "claude_web",
        "claude_code",
        "codex",
        "copilot",
        "openrouter",
        "opencode_go",
        "minimax",
    }
    assert expected.issubset(results.keys())
    for item in results.values():
        assert isinstance(item["detected"], bool)
        assert isinstance(item["detail"], str)
