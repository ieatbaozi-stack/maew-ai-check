"""Configuration persistence under %APPDATA%/maew-ai-check/config.json."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import APP_NAME

log = logging.getLogger("maew.config")

VALID_CAT_SKINS = ("orange", "greige", "black_yellow", "white", "choco")
VALID_THEMES = ("dark", "light")
VALID_MINIMAX_REGIONS = ("international", "china")


def app_data_dir() -> Path:
    override = os.environ.get("MAEW_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME
        return Path.home() / "AppData" / "Roaming" / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def webview_storage_dir() -> Path:
    """Dedicated isolated WebView2 profile folder (never touches user's main browser)."""
    return app_data_dir() / "webview2"


def local_usage_db_path() -> Path:
    return app_data_dir() / "claude_local.sqlite"


@dataclass
class ProviderSettings:
    antigravity: bool = True
    claude_web: bool = True
    claude_code: bool = True
    codex: bool = False
    copilot: bool = False
    openrouter: bool = False
    opencode_go: bool = False
    minimax: bool = False

    antigravity_cli_path: str | None = None
    antigravity_show_gemini: bool = True
    antigravity_show_third_party: bool = True
    claude_log_root: str | None = None
    copilot_username: str | None = None
    copilot_billing_org: str | None = None
    copilot_monthly_quota: int = 1500
    openrouter_daily_budget: float | None = None
    minimax_region: str = "international"


@dataclass
class WindowSettings:
    x: int | None = None
    y: int | None = None
    compact: bool = False
    always_on_top: bool = True
    cat_skin: str = "orange"
    theme: str = "dark"


@dataclass
class AppConfig:
    active_refresh_minutes: int = 5
    idle_max_refresh_minutes: int = 60
    providers: ProviderSettings = field(default_factory=ProviderSettings)
    window: WindowSettings = field(default_factory=WindowSettings)

    @classmethod
    def config_path(cls) -> Path:
        return app_data_dir() / "config.json"

    @classmethod
    def load(cls) -> AppConfig:
        path = cls.config_path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return cls()
            return cls.from_dict(raw)
        except Exception:  # noqa: BLE001
            log.exception("Failed to read config from %s; using defaults", path)
            return cls()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AppConfig:
        prov_raw = raw.get("providers") if isinstance(raw.get("providers"), dict) else {}
        win_raw = raw.get("window") if isinstance(raw.get("window"), dict) else {}

        active = _clamp_int(raw.get("active_refresh_minutes", 5), 1, 180, 5)
        idle_max = _clamp_int(raw.get("idle_max_refresh_minutes", 60), active, 240, 60)

        skin = str(win_raw.get("cat_skin", "orange"))
        if skin == "black_green":
            skin = "black_yellow"
        elif skin not in VALID_CAT_SKINS:
            skin = "orange"

        theme = str(win_raw.get("theme", "dark"))
        if theme not in VALID_THEMES:
            theme = "dark"

        mm_region = str(prov_raw.get("minimax_region", "international"))
        if mm_region not in VALID_MINIMAX_REGIONS:
            mm_region = "international"

        providers = ProviderSettings(
            antigravity=bool(prov_raw.get("antigravity", True)),
            claude_web=bool(prov_raw.get("claude_web", True)),
            claude_code=bool(prov_raw.get("claude_code", True)),
            codex=bool(prov_raw.get("codex", False)),
            copilot=bool(prov_raw.get("copilot", False)),
            openrouter=bool(prov_raw.get("openrouter", False)),
            opencode_go=bool(prov_raw.get("opencode_go", False)),
            minimax=bool(prov_raw.get("minimax", False)),
            antigravity_cli_path=_clean_str(prov_raw.get("antigravity_cli_path")),
            antigravity_show_gemini=bool(prov_raw.get("antigravity_show_gemini", True)),
            antigravity_show_third_party=bool(
                prov_raw.get("antigravity_show_third_party", True)
            ),
            claude_log_root=_clean_str(prov_raw.get("claude_log_root")),
            copilot_username=_clean_str(prov_raw.get("copilot_username")),
            copilot_billing_org=_clean_str(prov_raw.get("copilot_billing_org")),
            copilot_monthly_quota=_clamp_int(
                prov_raw.get("copilot_monthly_quota", 1500), 1, 1000000, 1500
            ),
            openrouter_daily_budget=_opt_positive_float(
                prov_raw.get("openrouter_daily_budget")
            ),
            minimax_region=mm_region,
        )
        window = WindowSettings(
            x=_opt_int(win_raw.get("x")),
            y=_opt_int(win_raw.get("y")),
            compact=bool(win_raw.get("compact", False)),
            always_on_top=bool(win_raw.get("always_on_top", True)),
            cat_skin=skin,
            theme=theme,
        )
        return cls(
            active_refresh_minutes=active,
            idle_max_refresh_minutes=idle_max,
            providers=providers,
            window=window,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self) -> None:
        path = self.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2),
            encoding="utf-8",
        )


def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(low, min(high, value))


def _opt_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _opt_positive_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _clean_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None
