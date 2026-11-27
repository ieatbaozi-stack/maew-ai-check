from __future__ import annotations

import json
from datetime import datetime, timezone

from maew.models import SnapshotStatus
from maew.providers.claude_logs import ClaudeCodeLocalProvider, parse_claude_log_line


def _line(msg_id: str, req_id: str, out_tokens: int, model: str = "claude-sonnet-4-6") -> bytes:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    obj = {
        "type": "assistant",
        "timestamp": ts,
        "requestId": req_id,
        "message": {
            "id": msg_id,
            "model": model,
            "usage": {
                "input_tokens": 1000,
                "output_tokens": out_tokens,
                "cache_read_input_tokens": 5000,
                "cache_creation_input_tokens": 200,
            },
        },
    }
    return (json.dumps(obj) + "\n").encode("utf-8")


def test_parse_ignores_synthetic_and_non_assistant():
    assert parse_claude_log_line(b'{"type":"user","message":{"content":"hi"}}\n') is None
    assert parse_claude_log_line(_line("m1", "r1", 10, model="<synthetic>")) is None


def test_incremental_sync_and_streaming_dedup(tmp_path):
    proj_dir = tmp_path / "projects" / "demo"
    proj_dir.mkdir(parents=True)
    log_file = proj_dir / "session.jsonl"
    db_file = tmp_path / "local.sqlite"

    # Write two streaming snapshots for the same (msg_1, req_1) — later output_tokens wins!
    log_file.write_bytes(_line("msg_1", "req_1", 10) + _line("msg_1", "req_1", 250))

    provider = ClaudeCodeLocalProvider(log_root=str(tmp_path / "projects"), db_path=db_file)
    snap1 = provider.fetch()
    assert snap1.status == SnapshotStatus.OK
    w5 = snap1.extra["windows"]["5h"]
    assert w5["messages"] == 1
    assert w5["tokens"]["output"] == 250

    # Append a second message incrementally
    with log_file.open("ab") as fh:
        fh.write(_line("msg_2", "req_2", 500))

    snap2 = provider.fetch()
    w5_2 = snap2.extra["windows"]["5h"]
    assert w5_2["messages"] == 2
    assert w5_2["tokens"]["output"] == 750
    assert w5_2["cost_usd"] > 0
