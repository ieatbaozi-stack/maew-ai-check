"""Main application controller: frameless Edge WebView2 widget + Tray + Serial Provider Runner."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import webview

from . import __version__
from .config import VALID_CAT_SKINS, AppConfig, app_data_dir, webview_storage_dir
from .models import SnapshotStatus, UsageSnapshot
from .providers import (
    AntigravityProvider,
    ClaudeCodeLocalProvider,
    ClaudeWebProvider,
    CodexProvider,
    CopilotProvider,
    MiniMaxProvider,
    OpenCodeGoProvider,
    OpenRouterProvider,
    ProviderRegistry,
)
from .providers.claude_web import CLAUDE_LOGIN_URL, CLAUDE_USAGE_URL
from .providers.codex import CODEX_LOGIN_URL, CODEX_USAGE_URL
from .scanner import scan_local_harnesses
from .scheduler import AdaptiveScheduler
from .secrets import SecretStore
from .tray import MaewTray

log = logging.getLogger("maew.app")

EXPANDED_SIZE = (312, 442)
COMPACT_SIZE = (274, 88)

ALLOWED_SECRET_KEYS = frozenset(
    {"github_pat", "openrouter_key", "opencode_go_key", "minimax_key"}
)

WEB_LOGIN_TARGETS: dict[str, tuple[str, str, str, str]] = {
    "claude_web": ("Claude", CLAUDE_LOGIN_URL, CLAUDE_USAGE_URL, "claude.ai"),
    "codex": ("Codex (ChatGPT)", CODEX_LOGIN_URL, CODEX_USAGE_URL, "chatgpt.com"),
}


def _frontend_index_path() -> str:
    return str((Path(__file__).resolve().parent / "frontend" / "index.html"))


def _setup_logging() -> None:
    log_dir = app_data_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "maew.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
    )


class JsApi:
    """Exposed safely to the local frontend via window.pywebview.api."""

    def __init__(self, app: MaewApp) -> None:
        self._app = app

    def get_state(self) -> dict[str, Any]:
        return self._app.build_frontend_state()

    def refresh_now(self) -> dict[str, Any]:
        self._app.request_refresh(manual=True)
        return {"ok": True}

    def set_compact(self, compact: bool) -> dict[str, Any]:
        self._app.set_compact(bool(compact))
        return {"ok": True}

    def set_cat_skin(self, skin: str) -> dict[str, Any]:
        self._app.set_cat_skin(skin)
        return {"ok": True}

    def toggle_always_on_top(self) -> dict[str, Any]:
        val = self._app.toggle_always_on_top()
        return {"always_on_top": val}

    def hide_to_tray(self) -> dict[str, Any]:
        self._app.hide_window()
        return {"ok": True}

    def scan_providers(self) -> dict[str, Any]:
        return self._app.scan_providers()

    def set_provider_secret(self, key_name: str, value: str | None) -> dict[str, Any]:
        ok = self._app.set_provider_secret(key_name, value)
        return {"ok": ok, "saved_keys": self._app.saved_key_flags()}

    def open_web_login(self, provider_id: str) -> dict[str, Any]:
        self._app.open_web_login(provider_id)
        return {"ok": True}

    def clear_web_session(self, provider_id: str) -> dict[str, Any]:
        self._app.clear_web_session(provider_id)
        return {"ok": True}

    # Backwards-compatible aliases
    def open_claude_login(self) -> dict[str, Any]:
        return self.open_web_login("claude_web")

    def clear_claude_session(self) -> dict[str, Any]:
        return self.clear_web_session("claude_web")

    def save_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        self._app.apply_settings_patch(patch)
        return self._app.build_frontend_state()


class MaewApp:
    def __init__(self) -> None:
        self._config = AppConfig.load()
        self._secrets = SecretStore(app_data_dir())
        self._scheduler = AdaptiveScheduler(
            active_minutes=self._config.active_refresh_minutes,
            max_minutes=self._config.idle_max_refresh_minutes,
        )
        self._registry = ProviderRegistry()
        self._snapshots: dict[str, UsageSnapshot] = {}
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._refreshing = False
        self._manual_pending = True
        self._next_refresh_at: datetime | None = None
        self._last_updated: datetime | None = None
        self._visible = True
        self._window: webview.Window | None = None
        self._login_window: webview.Window | None = None
        self._tray: MaewTray | None = None

        self._rebuild_providers()

    def _rebuild_providers(self) -> None:
        self._registry = ProviderRegistry()
        cfg = self._config.providers

        if cfg.claude_web:
            self._registry.register(ClaudeWebProvider(self._scrape_web_page))
        if cfg.claude_code:
            self._registry.register(ClaudeCodeLocalProvider(log_root=cfg.claude_log_root))
        if cfg.antigravity:
            self._registry.register(
                AntigravityProvider(
                    cli_path=cfg.antigravity_cli_path,
                    show_gemini=cfg.antigravity_show_gemini,
                    show_third_party=cfg.antigravity_show_third_party,
                )
            )
        if cfg.codex:
            self._registry.register(CodexProvider(self._scrape_web_page))
        if cfg.copilot:
            self._registry.register(
                CopilotProvider(
                    key_loader=lambda: self._secrets.get("github_pat"),
                    username=cfg.copilot_username,
                    billing_org=cfg.copilot_billing_org,
                    monthly_quota=cfg.copilot_monthly_quota,
                )
            )
        if cfg.openrouter:
            self._registry.register(
                OpenRouterProvider(
                    key_loader=lambda: self._secrets.get("openrouter_key"),
                    daily_budget=cfg.openrouter_daily_budget,
                )
            )
        if cfg.opencode_go:
            self._registry.register(
                OpenCodeGoProvider(key_loader=lambda: self._secrets.get("opencode_go_key"))
            )
        if cfg.minimax:
            self._registry.register(
                MiniMaxProvider(
                    key_loader=lambda: self._secrets.get("minimax_key"),
                    region=cfg.minimax_region,
                )
            )

    def scan_providers(self) -> dict[str, Any]:
        return scan_local_harnesses(self._secrets)

    def saved_key_flags(self) -> dict[str, bool]:
        return {k: bool(self._secrets.get(k)) for k in ALLOWED_SECRET_KEYS}

    def set_provider_secret(self, key_name: str, value: str | None) -> bool:
        if key_name not in ALLOWED_SECRET_KEYS:
            return False
        cleaned = value.strip() if isinstance(value, str) else None
        self._secrets.set(key_name, cleaned or None)
        self.request_refresh(manual=True)
        return True

    # ----- Isolated WebView2 scraping & login (Claude.ai & Codex/ChatGPT) -----

    def _scrape_web_page(self, url: str, extractor_js: str) -> dict[str, Any] | None:
        if self._stop_event.is_set() or self._login_window is not None:
            return None

        loaded = threading.Event()
        win = webview.create_window(
            "maew sync",
            url=url,
            width=1280,
            height=900,
            hidden=True,
        )
        if win is None:
            return None
        try:
            win.events.loaded += lambda: loaded.set()
            if not loaded.wait(timeout=18.0):
                log.warning("Hidden WebView2 timed out loading %s", urlparse(url).netloc)
                return None

            time.sleep(3.5)
            result = None
            for _attempt in range(6):
                if self._stop_event.is_set():
                    return None
                try:
                    result = win.evaluate_js(extractor_js)
                except Exception as exc:  # noqa: BLE001
                    log.debug("Web extractor eval retry: %s", exc)
                    result = None
                if isinstance(result, dict) and not result.get("__retry"):
                    return result
                time.sleep(1.2)
            return result if isinstance(result, dict) else None
        finally:
            try:
                win.destroy()
            except Exception:  # noqa: BLE001
                pass

    def open_web_login(self, provider_id: str) -> None:
        target = WEB_LOGIN_TARGETS.get(provider_id)
        if target is None:
            return
        label, login_url, _usage_url, expected_host = target

        if self._login_window is not None:
            try:
                self._login_window.show()
            except Exception:  # noqa: BLE001
                pass
            return

        win = webview.create_window(
            f"Sign in to {label} — maew usage",
            url=login_url,
            width=520,
            height=680,
            resizable=True,
            on_top=False,
        )
        if win is None:
            return
        self._login_window = win

        def _on_closed() -> None:
            self._login_window = None
            self.request_refresh(manual=True)

        win.events.closed += _on_closed

        def _watch_login() -> None:
            deadline = time.monotonic() + 300.0
            while (
                self._login_window is win
                and not self._stop_event.is_set()
                and time.monotonic() < deadline
            ):
                time.sleep(1.0)
                try:
                    current = win.get_current_url() or ""
                except Exception:  # noqa: BLE001
                    break
                parsed = urlparse(current)
                path = (parsed.path or "").lower()
                if (
                    parsed.hostname == expected_host
                    and path
                    and not path.startswith("/login")
                    and not path.startswith("/auth/login")
                    and not path.startswith("/logout")
                    and not path.startswith("/oauth")
                ):
                    time.sleep(1.5)
                    try:
                        win.destroy()
                    except Exception:  # noqa: BLE001
                        pass
                    break

        threading.Thread(target=_watch_login, name=f"maew-login-{provider_id}", daemon=True).start()

    def clear_web_session(self, provider_id: str) -> None:
        target = WEB_LOGIN_TARGETS.get(provider_id)
        if target is None:
            return
        label, _login_url, usage_url, _host = target

        def _clear() -> None:
            win = webview.create_window(
                "maew clear session",
                url=usage_url,
                width=400,
                height=300,
                hidden=True,
            )
            if win is not None:
                try:
                    time.sleep(1.0)
                    win.clear_cookies()
                except Exception:  # noqa: BLE001
                    pass
                finally:
                    try:
                        win.destroy()
                    except Exception:  # noqa: BLE001
                        pass
            with self._lock:
                self._snapshots[provider_id] = UsageSnapshot(
                    provider=provider_id,
                    display_name=label.split(" ")[0],
                    status=SnapshotStatus.AUTH_REQUIRED,
                    error=f"Session cleared — click Connect to sign in to {label}",
                )
            self._push_state()

        threading.Thread(target=_clear, name=f"maew-clear-{provider_id}", daemon=True).start()

    # ----- State & UI synchronization -----

    def build_frontend_state(self) -> dict[str, Any]:
        with self._lock:
            snaps = {k: v.to_dict() for k, v in self._snapshots.items()}
            refreshing = self._refreshing
            next_at = self._next_refresh_at
            updated = self._last_updated

        next_label = "--"
        if next_at is not None:
            mins = max(1, int(round((next_at - datetime.now()).total_seconds() / 60.0)))
            next_label = f"{mins}m"

        return {
            "version": __version__,
            "config": self._config.to_dict(),
            "saved_keys": self.saved_key_flags(),
            "snapshots": snaps,
            "refreshing": refreshing,
            "next_refresh_label": next_label,
            "updated_label": updated.strftime("%H:%M") if updated else "starting...",
        }

    def _push_state(self) -> None:
        if self._window is None or self._stop_event.is_set():
            return
        payload = json.dumps(self.build_frontend_state())
        try:
            self._window.evaluate_js(
                f"window.maewReceiveState && window.maewReceiveState({payload});"
            )
        except Exception:  # noqa: BLE001
            pass
        self._update_tray_tooltip()

    def _update_tray_tooltip(self) -> None:
        if self._tray is None:
            return
        parts = [f"maew usage {__version__}"]
        with self._lock:
            for snap in self._snapshots.values():
                if snap.status != SnapshotStatus.OK:
                    continue
                peak = snap.max_percent()
                if peak is not None:
                    parts.append(f"{snap.display_name}: {peak:.0f}%")
        self._tray.update(tooltip=" | ".join(parts))

    # ----- Window & Settings Controls -----

    def set_compact(self, compact: bool) -> None:
        self._config.window.compact = compact
        self._config.save()
        if self._window is not None:
            w, h = COMPACT_SIZE if compact else EXPANDED_SIZE
            try:
                self._window.resize(w, h)
            except Exception:  # noqa: BLE001
                pass
        self._push_state()

    def toggle_compact(self) -> None:
        self.set_compact(not self._config.window.compact)

    def set_cat_skin(self, skin: str) -> None:
        if skin not in VALID_CAT_SKINS:
            return
        self._config.window.cat_skin = skin
        self._config.save()
        if self._tray is not None:
            self._tray.update(skin=skin)

    def toggle_always_on_top(self) -> bool:
        self._config.window.always_on_top = not self._config.window.always_on_top
        self._config.save()
        if self._window is not None:
            try:
                self._window.on_top = self._config.window.always_on_top
            except Exception:  # noqa: BLE001
                pass
        self._push_state()
        return self._config.window.always_on_top

    def apply_settings_patch(self, patch: dict[str, Any]) -> None:
        merged = self._config.to_dict()
        for key in ("active_refresh_minutes", "idle_max_refresh_minutes"):
            if key in patch:
                merged[key] = patch[key]
        if isinstance(patch.get("window"), dict):
            merged["window"].update(patch["window"])
        if isinstance(patch.get("providers"), dict):
            merged["providers"].update(patch["providers"])

        self._config = AppConfig.from_dict(merged)
        self._config.save()
        self._scheduler.active_minutes = self._config.active_refresh_minutes
        self._scheduler.max_minutes = self._config.idle_max_refresh_minutes
        self._rebuild_providers()

        if self._window is not None:
            try:
                self._window.on_top = self._config.window.always_on_top
            except Exception:  # noqa: BLE001
                pass
        if self._tray is not None:
            self._tray.update(skin=self._config.window.cat_skin)

        enabled_ids = set(self._registry.ids())
        with self._lock:
            for pid in list(self._snapshots):
                if pid not in enabled_ids:
                    self._snapshots.pop(pid, None)

        self.request_refresh(manual=True)

    def hide_window(self) -> None:
        if self._window is not None:
            try:
                self._window.hide()
                self._visible = False
            except Exception:  # noqa: BLE001
                pass

    def toggle_window(self) -> None:
        if self._window is None:
            return
        try:
            if self._visible:
                self._window.hide()
                self._visible = False
            else:
                self._window.show()
                self._visible = True
        except Exception:  # noqa: BLE001
            pass

    # ----- Background Refresh Loop -----

    def request_refresh(self, *, manual: bool = True) -> None:
        if manual:
            self._manual_pending = True
            self._scheduler.mark_manual_activity()
        self._wake_event.set()

    def _run_refresh_cycle(self, *, manual: bool) -> None:
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            with self._lock:
                self._refreshing = True
            self._push_state()

            for provider in self._registry.all():
                if self._stop_event.is_set():
                    break
                snap = provider.fetch()
                with self._lock:
                    prev = self._snapshots.get(provider.id)
                    if (
                        snap.status == SnapshotStatus.ERROR
                        and not snap.metrics
                        and prev is not None
                        and prev.metrics
                    ):
                        snap = replace(snap, metrics=list(prev.metrics), stale=True)
                    self._snapshots[provider.id] = snap
                    self._last_updated = datetime.now()
                self._push_state()

            with self._lock:
                decision = self._scheduler.record_cycle(self._snapshots, manual=manual)
                self._next_refresh_at = decision.next_refresh_at
                self._refreshing = False
            self._push_state()
        finally:
            self._refresh_lock.release()

    def _scheduler_loop(self) -> None:
        self._stop_event.wait(0.8)
        while not self._stop_event.is_set():
            manual = self._manual_pending
            self._manual_pending = False
            self._wake_event.clear()
            self._run_refresh_cycle(manual=manual)

            with self._lock:
                decision = self._scheduler.next_decision(self._snapshots)
                self._next_refresh_at = decision.next_refresh_at
                wait_s = decision.delay_seconds
            self._push_state()

            end = time.monotonic() + wait_s
            while not self._stop_event.is_set() and not self._wake_event.is_set():
                remaining = end - time.monotonic()
                if remaining <= 0:
                    break
                self._wake_event.wait(timeout=min(1.0, remaining))

    # ----- Lifecycle -----

    def quit(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._tray is not None:
            self._tray.stop()
        if self._login_window is not None:
            try:
                self._login_window.destroy()
            except Exception:  # noqa: BLE001
                pass
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:  # noqa: BLE001
                pass

    def run(self) -> None:
        _setup_logging()
        log.info("Starting maew usage %s (data=%s)", __version__, app_data_dir())

        storage_dir = webview_storage_dir()
        storage_dir.mkdir(parents=True, exist_ok=True)

        w, h = COMPACT_SIZE if self._config.window.compact else EXPANDED_SIZE
        bg = "#f7f6f2" if self._config.window.theme == "light" else "#161618"

        self._window = webview.create_window(
            "maew usage",
            url=_frontend_index_path(),
            js_api=JsApi(self),
            width=w,
            height=h,
            x=self._config.window.x,
            y=self._config.window.y,
            resizable=False,
            frameless=True,
            easy_drag=False,
            shadow=True,
            on_top=self._config.window.always_on_top,
            background_color=bg,
        )

        self._tray = MaewTray(
            skin=self._config.window.cat_skin,
            on_toggle=self.toggle_window,
            on_refresh=lambda: self.request_refresh(manual=True),
            on_compact=self.toggle_compact,
            on_quit=self.quit,
        )

        def _on_start() -> None:
            assert self._tray is not None
            self._tray.start()
            threading.Thread(
                target=self._scheduler_loop,
                name="maew-scheduler",
                daemon=True,
            ).start()

        webview.start(
            func=_on_start,
            gui="edgechromium",
            private_mode=False,
            storage_path=str(storage_dir),
            debug=False,
        )


def main() -> int:
    MaewApp().run()
    return 0
