"""Core data models shared across all providers and the UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SnapshotStatus(str, Enum):
    OK = "ok"
    AUTH_REQUIRED = "auth_required"
    ERROR = "error"
    LOADING = "loading"
    DISABLED = "disabled"


@dataclass
class UsageMetric:
    label: str
    percent_used: float | None = None
    resets_at: datetime | None = None
    reset_label: str | None = None
    note: str | None = None
    window_hours: float | None = None
    group: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "percent_used": round(self.percent_used, 1)
            if self.percent_used is not None
            else None,
            "resets_at": self.resets_at.isoformat() if self.resets_at else None,
            "reset_label": self.reset_label,
            "note": self.note,
            "window_hours": self.window_hours,
            "group": self.group,
        }


@dataclass
class UsageSnapshot:
    provider: str
    display_name: str
    status: SnapshotStatus
    metrics: list[UsageMetric] = field(default_factory=list)
    error: str | None = None
    fetched_at: datetime = field(default_factory=datetime.now)
    stale: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def max_percent(self) -> float | None:
        vals = [m.percent_used for m in self.metrics if m.percent_used is not None]
        return max(vals) if vals else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "display_name": self.display_name,
            "status": self.status.value,
            "metrics": [m.to_dict() for m in self.metrics],
            "error": self.error,
            "fetched_at": self.fetched_at.isoformat(),
            "stale": self.stale,
            "extra": self.extra,
        }


@dataclass
class TokenCounts:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    reasoning: int = 0

    def add(self, other: TokenCounts) -> None:
        self.input += other.input
        self.output += other.output
        self.cache_read += other.cache_read
        self.cache_write_5m += other.cache_write_5m
        self.cache_write_1h += other.cache_write_1h
        self.reasoning += other.reasoning

    @property
    def total(self) -> int:
        return (
            self.input
            + self.output
            + self.cache_read
            + self.cache_write_5m
            + self.cache_write_1h
        )

    def to_dict(self) -> dict[str, int]:
        data = asdict(self)
        data["total"] = self.total
        return data
