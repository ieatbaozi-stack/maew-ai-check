"""Offline local Claude Code usage & estimated API cost tracker.

Reads JSONL session logs under:
  1. $CLAUDE_CONFIG_DIR/projects/**/*.jsonl
  2. ~/.claude/projects/**/*.jsonl
  3. ~/.config/claude/projects/**/*.jsonl

Privacy & performance:
- 100% offline. Never reads prompt text, code, or tool outputs.
- Byte-level pre-filter skips lines without '"usage"' and '"assistant"'.
- Incremental import via SQLite byte offsets + 256-byte tail SHA1 hash.
- Deduplicates streaming assistant messages by (message.id, requestId).
- Pricing-on-read using bundled rates.json + optional %APPDATA%/maew-ai-check/rates.override.json.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from typing import Any

from ..config import app_data_dir, local_usage_db_path
from ..models import SnapshotStatus, TokenCounts, UsageMetric, UsageSnapshot
from .base import Provider

log = logging.getLogger("maew.providers.claude_logs")

_USAGE_MARKER = b'"usage"'
_ASSISTANT_MARKER = b'"assistant"'
_SYNTHETIC_MODEL = "<synthetic>"
_TAIL_BYTES = 256
_DATE_SUFFIX = re.compile(r"-\d{8}$")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_files (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    read_offset INTEGER NOT NULL,
    tail_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claude_messages (
    message_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    ts_utc TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_read INTEGER NOT NULL,
    cache_write_5m INTEGER NOT NULL,
    cache_write_1h INTEGER NOT NULL,
    reasoning INTEGER NOT NULL,
    PRIMARY KEY (message_id, request_id)
);
CREATE INDEX IF NOT EXISTS idx_claude_messages_ts ON claude_messages (ts_utc);
"""


@dataclass(frozen=True)
class ClaudeLogMessage:
    message_id: str
    request_id: str
    timestamp: datetime  # aware UTC
    model: str
    tokens: TokenCounts


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    return 0


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def parse_claude_log_line(raw: bytes) -> ClaudeLogMessage | None:
    if _USAGE_MARKER not in raw or _ASSISTANT_MARKER not in raw:
        return None
    try:
        entry = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(entry, dict) or entry.get("type") != "assistant":
        return None
    message = entry.get("message")
    if not isinstance(message, dict):
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    model = message.get("model")
    if model == _SYNTHETIC_MODEL:
        return None
    message_id = message.get("id")
    ts = _parse_timestamp(entry.get("timestamp"))
    if not isinstance(message_id, str) or not message_id or ts is None:
        return None
    request_id = entry.get("requestId")
    if not isinstance(request_id, str):
        request_id = ""

    cache_creation = usage.get("cache_creation")
    if isinstance(cache_creation, dict):
        write_5m = _as_int(cache_creation.get("ephemeral_5m_input_tokens"))
        write_1h = _as_int(cache_creation.get("ephemeral_1h_input_tokens"))
    else:
        write_5m = _as_int(usage.get("cache_creation_input_tokens"))
        write_1h = 0

    details = usage.get("output_tokens_details")
    reasoning = _as_int(details.get("thinking_tokens")) if isinstance(details, dict) else 0
    tokens = TokenCounts(
        input=_as_int(usage.get("input_tokens")),
        output=_as_int(usage.get("output_tokens")),
        cache_read=_as_int(usage.get("cache_read_input_tokens")),
        cache_write_5m=write_5m,
        cache_write_1h=write_1h,
        reasoning=reasoning,
    )
    return ClaudeLogMessage(
        message_id=message_id,
        request_id=request_id,
        timestamp=ts,
        model=model if isinstance(model, str) and model else "unknown",
        tokens=tokens,
    )


def default_claude_log_roots(override: str | None = None) -> list[Path]:
    if override:
        return [Path(override).expanduser()]
    roots: list[Path] = []
    env_dir = os.environ.get("CLAUDE_CONFIG_DIR", "")
    for part in env_dir.split(os.pathsep) if env_dir else []:
        part = part.strip()
        if part:
            roots.append(Path(part).expanduser() / "projects")
    home = Path.home()
    roots.append(home / ".claude" / "projects")
    roots.append(home / ".config" / "claude" / "projects")

    seen: set[str] = set()
    unique: list[Path] = []
    for p in roots:
        key = os.path.normcase(str(p))
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def load_rates() -> dict[str, dict[str, float]]:
    models: dict[str, dict[str, float]] = {}
    try:
        bundled_text = (
            resources.files("maew.providers")
            .joinpath("rates.json")
            .read_text(encoding="utf-8")
        )
        bundled = json.loads(bundled_text)
        for name, entry in (bundled.get("models") or {}).items():
            if isinstance(entry, dict) and isinstance(entry.get("rates"), dict):
                models[name] = {k: float(v) for k, v in entry["rates"].items()}
    except Exception:  # noqa: BLE001
        log.exception("Could not load bundled rates.json")

    override_path = app_data_dir() / "rates.override.json"
    if override_path.is_file():
        try:
            override = json.loads(override_path.read_text(encoding="utf-8"))
            for name, entry in (override.get("models") or {}).items():
                if isinstance(entry, dict) and isinstance(entry.get("rates"), dict):
                    models[name] = {k: float(v) for k, v in entry["rates"].items()}
        except Exception:  # noqa: BLE001
            log.warning("Could not parse %s", override_path)
    return models


def estimate_cost(model: str, tokens: TokenCounts, rates: dict[str, dict[str, float]]) -> float | None:
    price = rates.get(model) or rates.get(_DATE_SUFFIX.sub("", model))
    if price is None:
        return None
    return (
        tokens.input * price.get("input", 0.0)
        + tokens.output * price.get("output", 0.0)
        + tokens.cache_read * price.get("cache_read", 0.0)
        + tokens.cache_write_5m * price.get("cache_write_5m", 0.0)
        + tokens.cache_write_1h * price.get("cache_write_1h", 0.0)
    ) / 1_000_000.0


def _tail_hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _read_tail(path: Path, offset: int) -> bytes:
    start = max(0, offset - _TAIL_BYTES)
    with path.open("rb") as fh:
        fh.seek(start)
        return fh.read(offset - start)


def _format_tokens(count: int) -> str:
    if count >= 1_000_000_000:
        return f"{count / 1_000_000_000:.2f}B"
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)


def _format_usd(amount: float) -> str:
    if amount >= 100:
        return f"${amount:,.0f}"
    return f"${amount:,.2f}"


class ClaudeCodeLocalProvider(Provider):
    id = "claude_code"
    display_name = "Claude Code (Local)"
    short_label = "CC"
    kind = "local_logs"

    def __init__(
        self,
        *,
        log_root: str | None = None,
        db_path: Path | None = None,
    ) -> None:
        self.log_root = log_root
        self._db_path = db_path or local_usage_db_path()

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        return conn

    def sync_logs(self) -> tuple[int, int]:
        """Incrementally import new JSONL lines. Returns (files_seen, messages_imported)."""
        roots = default_claude_log_roots(self.log_root)
        files: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            if not root.is_dir():
                continue
            for dirpath, _dirnames, filenames in os.walk(root):
                for name in filenames:
                    if not name.endswith(".jsonl"):
                        continue
                    path = Path(dirpath) / name
                    try:
                        key = os.path.normcase(os.path.realpath(path))
                    except OSError:
                        continue
                    if key in seen:
                        continue
                    seen.add(key)
                    files.append(path)

        imported = 0
        conn = self._connect()
        try:
            for path in files:
                try:
                    stat = path.stat()
                except OSError:
                    continue
                key = os.path.normcase(os.path.realpath(path))
                row = conn.execute(
                    "SELECT size, mtime, read_offset, tail_hash FROM source_files WHERE path = ?",
                    (key,),
                ).fetchone()

                start_offset = 0
                tail = b""
                if row is not None:
                    prev_size, prev_mtime, prev_offset, prev_hash = row
                    if stat.st_size == prev_size and stat.st_mtime == prev_mtime:
                        continue
                    if stat.st_size >= prev_offset > 0:
                        try:
                            candidate_tail = _read_tail(path, prev_offset)
                            if _tail_hash(candidate_tail) == prev_hash:
                                start_offset = prev_offset
                                tail = candidate_tail
                        except OSError:
                            start_offset = 0

                batch: dict[tuple[str, str], ClaudeLogMessage] = {}
                pos = start_offset
                try:
                    with path.open("rb") as fh:
                        fh.seek(start_offset)
                        for line in fh:
                            if not line.endswith(b"\n"):
                                break
                            pos += len(line)
                            tail = (tail + line)[-_TAIL_BYTES:]
                            msg = parse_claude_log_line(line)
                            if msg is not None:
                                batch[(msg.message_id, msg.request_id)] = msg
                except OSError:
                    continue

                with conn:
                    if batch:
                        conn.executemany(
                            """
                            INSERT INTO claude_messages (
                                message_id, request_id, ts_utc, model,
                                input_tokens, output_tokens, cache_read,
                                cache_write_5m, cache_write_1h, reasoning
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(message_id, request_id) DO UPDATE SET
                                ts_utc=excluded.ts_utc,
                                model=excluded.model,
                                input_tokens=excluded.input_tokens,
                                output_tokens=excluded.output_tokens,
                                cache_read=excluded.cache_read,
                                cache_write_5m=excluded.cache_write_5m,
                                cache_write_1h=excluded.cache_write_1h,
                                reasoning=excluded.reasoning
                            """,
                            [
                                (
                                    m.message_id,
                                    m.request_id,
                                    m.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    m.model,
                                    m.tokens.input,
                                    m.tokens.output,
                                    m.tokens.cache_read,
                                    m.tokens.cache_write_5m,
                                    m.tokens.cache_write_1h,
                                    m.tokens.reasoning,
                                )
                                for m in batch.values()
                            ],
                        )
                        imported += len(batch)
                    conn.execute(
                        """
                        INSERT INTO source_files (path, size, mtime, read_offset, tail_hash)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(path) DO UPDATE SET
                            size=excluded.size,
                            mtime=excluded.mtime,
                            read_offset=excluded.read_offset,
                            tail_hash=excluded.tail_hash
                        """,
                        (key, stat.st_size, stat.st_mtime, pos, _tail_hash(tail)),
                    )
        finally:
            conn.close()
        return len(files), imported

    def query_summary(self, since_utc: datetime) -> dict[str, Any]:
        rates = load_rates()
        since_str = since_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT model,
                       COUNT(*),
                       SUM(input_tokens),
                       SUM(output_tokens),
                       SUM(cache_read),
                       SUM(cache_write_5m),
                       SUM(cache_write_1h),
                       SUM(reasoning)
                FROM claude_messages
                WHERE ts_utc >= ?
                GROUP BY model
                """,
                (since_str,),
            ).fetchall()
        finally:
            conn.close()

        total_tokens = TokenCounts()
        total_messages = 0
        total_cost = 0.0
        has_unpriced = False
        by_model: list[dict[str, Any]] = []

        for model, count, inp, out, cr, cw5, cw1, reas in rows:
            tc = TokenCounts(
                input=inp or 0,
                output=out or 0,
                cache_read=cr or 0,
                cache_write_5m=cw5 or 0,
                cache_write_1h=cw1 or 0,
                reasoning=reas or 0,
            )
            cost = estimate_cost(model, tc, rates)
            if cost is None:
                has_unpriced = True
            else:
                total_cost += cost
            total_tokens.add(tc)
            total_messages += count or 0
            by_model.append(
                {
                    "model": model,
                    "messages": count or 0,
                    "tokens": tc.to_dict(),
                    "tokens_fmt": _format_tokens(tc.total),
                    "cost_usd": round(cost, 4) if cost is not None else None,
                    "cost_fmt": _format_usd(cost) if cost is not None else "N/A",
                }
            )

        by_model.sort(key=lambda item: -(item["cost_usd"] or 0.0))
        return {
            "messages": total_messages,
            "tokens": total_tokens.to_dict(),
            "tokens_fmt": _format_tokens(total_tokens.total),
            "cost_usd": round(total_cost, 4),
            "cost_fmt": _format_usd(total_cost),
            "has_unpriced": has_unpriced,
            "by_model": by_model,
        }

    def fetch(self) -> UsageSnapshot:
        files_seen, _imported = self.sync_logs()
        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now()
        start_today_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_today_utc = start_today_local.astimezone(timezone.utc)

        summary_5h = self.query_summary(now_utc - timedelta(hours=5))
        summary_today = self.query_summary(start_today_utc)
        summary_7d = self.query_summary(now_utc - timedelta(days=7))

        metrics = [
            UsageMetric(
                label=f"5h: {summary_5h['tokens_fmt']} · {summary_5h['cost_fmt']}",
                percent_used=None,
                note=f"{summary_5h['messages']} assistant turns in last 5h",
                group="Local",
            ),
            UsageMetric(
                label=f"Today: {summary_today['tokens_fmt']} · {summary_today['cost_fmt']}",
                percent_used=None,
                note=f"{summary_today['messages']} turns today",
                group="Local",
            ),
            UsageMetric(
                label=f"7d: {summary_7d['tokens_fmt']} · {summary_7d['cost_fmt']}",
                percent_used=None,
                note=f"{summary_7d['messages']} turns in last 7 days ({files_seen} log files)",
                group="Local",
            ),
        ]
        return UsageSnapshot(
            provider=self.id,
            display_name=self.display_name,
            status=SnapshotStatus.OK,
            metrics=metrics,
            extra={
                "files_seen": files_seen,
                "windows": {
                    "5h": summary_5h,
                    "today": summary_today,
                    "7d": summary_7d,
                },
            },
        )
