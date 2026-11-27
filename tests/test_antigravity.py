from __future__ import annotations

import pytest

from maew.models import SnapshotStatus
from maew.providers.antigravity import (
    AntigravityProvider,
    build_antigravity_snapshot,
    decode_agy_output,
    reset_latch_for_tests,
)


def _sample_payload() -> dict:
    return {
        "status": "SUCCESS",
        "num_turns": 0,
        "usage": {"total_tokens": 0},
        "command": {
            "name": "usage",
            "data": {
                "groups": [
                    {
                        "name": "Gemini Models",
                        "buckets": [
                            {
                                "id": "gemini-weekly",
                                "window": "weekly",
                                "remaining_fraction": 0.90,
                                "reset_time": "2026-12-04T03:58:22Z",
                            },
                            {
                                "id": "gemini-5h",
                                "window": "5h",
                                "remaining_fraction": 0.70,
                                "reset_time": "2026-11-27T08:58:22Z",
                            },
                        ],
                    },
                    {
                        "name": "Claude and GPT models",
                        "buckets": [
                            {
                                "id": "3p-5h",
                                "window": "5h",
                                "remaining_fraction": 1.0,
                                "reset_time": "1970-01-01T00:00:00Z",
                            }
                        ],
                    },
                ]
            },
        },
    }


def test_build_snapshot_orders_5h_before_weekly_and_handles_1970_idle():
    snap = build_antigravity_snapshot(_sample_payload())
    assert snap.status == SnapshotStatus.OK
    assert [m.label for m in snap.metrics] == ["5h", "7d", "5h"]
    assert [m.group for m in snap.metrics] == ["Gemini Models", "Gemini Models", "Claude & GPT"]
    assert snap.metrics[0].percent_used == pytest.approx(30.0)
    assert snap.metrics[1].percent_used == pytest.approx(10.0)
    assert snap.metrics[2].percent_used == pytest.approx(0.0)
    assert snap.metrics[2].resets_at is None
    assert snap.metrics[2].reset_label == "idle"


def test_safety_latch_triggers_on_nonzero_tokens():
    bad = _sample_payload()
    bad["num_turns"] = 1
    bad["usage"]["total_tokens"] = 120
    with pytest.raises(RuntimeError, match="Safety pause"):
        build_antigravity_snapshot(bad)


def test_decode_output_skips_leading_noise():
    stdout = 'some warning line\n{"status": "SUCCESS", "num_turns": 0}\n'
    parsed = decode_agy_output(stdout)
    assert parsed["status"] == "SUCCESS"


def test_provider_latches_after_spent_tokens(monkeypatch):
    reset_latch_for_tests()
    calls = 0

    class FakeProc:
        returncode = 0
        stdout = '{"status":"SUCCESS","num_turns":1,"usage":{"total_tokens":50}}'
        stderr = ""

    def fake_invoke(_exe):
        nonlocal calls
        calls += 1
        return FakeProc()

    monkeypatch.setattr("maew.providers.antigravity.resolve_cli", lambda _: "agy.exe")
    monkeypatch.setattr("maew.providers.antigravity.invoke_agy_cli", fake_invoke)

    provider = AntigravityProvider()
    first = provider.fetch()
    second = provider.fetch()

    assert first.status == SnapshotStatus.ERROR
    assert "Safety pause" in (first.error or "")
    assert second.status == SnapshotStatus.ERROR
    assert calls == 1  # Never invokes agy a second time!
    reset_latch_for_tests()
