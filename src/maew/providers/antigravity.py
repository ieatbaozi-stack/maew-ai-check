"""Antigravity CLI quota provider (`agy --print /quota`).

Security & safety guarantees:
- Always uses argument list (never shell=True).
- Runs in a fresh temporary working directory with stdin=DEVNULL and CREATE_NO_WINDOW.
- Sets AGY_CLI_DISABLE_AUTO_UPDATE=true so background updaters never pop consoles.
- Enforces a 60s hard timeout with Windows process-tree kill (taskkill /T /F).
- Safety latch: if num_turns > 0 or usage.total_tokens > 0 (meaning a broken CLI
  version sent /quota as a normal model prompt), permanently pauses polling for
  this process so it can NEVER burn user quota.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..models import SnapshotStatus, UsageMetric, UsageSnapshot
from .base import Provider

_CLI_TIMEOUT_SECONDS = 60
_KILL_GRACE_SECONDS = 5
_AGY_ENV_OVERRIDES = {"AGY_CLI_DISABLE_AUTO_UPDATE": "true"}
_LATCH_ERROR = (
    "Safety pause: agy did not treat /quota as a zero-token built-in command. "
    "Polling stopped to protect your quota. Update agy and restart Maew."
)

_PROCESS_LATCHED_ERROR: str | None = None


def reset_latch_for_tests() -> None:
    global _PROCESS_LATCHED_ERROR
    _PROCESS_LATCHED_ERROR = None


def normalize_cli_path(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in "\"'":
        normalized = normalized[1:-1].strip()
    normalized = os.path.expandvars(os.path.expanduser(normalized)).strip()
    return normalized or None


def is_agy_file_name(path: str) -> bool:
    return Path(path).stem.lower() == "agy"


def resolve_cli(cli_path: str | None = None) -> str | None:
    configured = normalize_cli_path(cli_path)
    if configured:
        return configured if Path(configured).is_file() else None

    found = shutil.which("agy")
    if found:
        return found

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidate = Path(local_app_data) / "agy" / "bin" / "agy.exe"
            if candidate.is_file():
                return str(candidate)
    return None


def _taskkill_exe() -> str:
    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if system_root:
        return str(Path(system_root) / "System32" / "taskkill.exe")
    return "taskkill"


def _kill_process_tree(proc: subprocess.Popen[str]) -> None:
    if sys.platform == "win32":
        try:
            killer = subprocess.Popen(
                [_taskkill_exe(), "/PID", str(proc.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                killer.wait(timeout=_KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                killer.kill()
        except OSError:
            pass
    else:
        try:
            os.killpg(proc.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


def invoke_agy_cli(exe: str) -> subprocess.CompletedProcess[str]:
    args = [
        exe,
        "--print",
        "/quota",
        "--output-format",
        "json",
        "--mode",
        "plan",
        "--sandbox",
        "--print-timeout",
        "30s",
    ]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as cwd:
        env = os.environ.copy()
        env.update(_AGY_ENV_OVERRIDES)
        proc = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            start_new_session=sys.platform != "win32",
            env=env,
        )
        try:
            stdout, stderr = proc.communicate(timeout=_CLI_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            try:
                proc.communicate(timeout=_KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                pass
            raise subprocess.TimeoutExpired(args, _CLI_TIMEOUT_SECONDS) from None
        except BaseException:
            _kill_process_tree(proc)
            raise
        return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)


def decode_agy_output(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout.strip())
        if isinstance(payload, dict):
            return payload
    except (json.JSONDecodeError, TypeError):
        pass

    for line in reversed(stdout.splitlines()):
        try:
            payload = json.loads(line.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict):
            return payload
    raise ValueError("Unexpected agy output: stdout is not JSON")


def _parse_reset_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        # Antigravity emits 1970-01-01T00:00:00Z for unused/idle buckets.
        if parsed.year <= 1971:
            return None
        return parsed
    except (ValueError, OverflowError):
        return None


def build_antigravity_snapshot(
    payload: dict[str, Any],
    *,
    show_gemini: bool = True,
    show_third_party: bool = True,
) -> UsageSnapshot:
    command = payload.get("command")
    usage = payload.get("usage")
    num_turns = payload.get("num_turns")
    total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None

    spent_tokens = (isinstance(num_turns, (int, float)) and num_turns > 0) or (
        isinstance(total_tokens, (int, float)) and total_tokens > 0
    )
    indeterminate_usage = (
        "command" not in payload
        and "num_turns" not in payload
        and not (isinstance(usage, dict) and "total_tokens" in usage)
    )
    if spent_tokens or indeterminate_usage:
        raise RuntimeError(_LATCH_ERROR)

    if payload.get("status") != "SUCCESS":
        raise ValueError(f"agy error: {payload.get('error', payload.get('status'))}")
    if num_turns != 0 or not isinstance(usage, dict) or total_tokens != 0:
        raise ValueError("Unexpected agy output: non-zero turn or token count")
    if not isinstance(command, dict) or command.get("name") != "usage":
        raise ValueError("Unexpected agy output: command.name is not usage")

    data = command.get("data")
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, list):
        raise ValueError("Unexpected agy output: command.data.groups missing")

    metrics: list[UsageMetric] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        buckets = group.get("buckets")
        if not isinstance(buckets, list):
            continue

        group_metrics: list[tuple[int, UsageMetric]] = []
        for bucket in buckets:
            if not isinstance(bucket, dict):
                continue
            bucket_id = str(bucket.get("id") or "")
            if bucket_id.startswith("gemini-"):
                group_label = "Gemini Models"
                if not show_gemini:
                    continue
            elif bucket_id.startswith("3p-"):
                group_label = "Claude & GPT"
                if not show_third_party:
                    continue
            else:
                group_label = str(group.get("name") or "Quota")

            window_val = bucket.get("window")
            if window_val == "5h":
                window_text = "5h"
                window_hours = 5.0
                order = 0
            elif window_val == "weekly":
                window_text = "7d"
                window_hours = 168.0
                order = 1
            else:
                window_text = str(window_val) if window_val is not None else ""
                window_hours = None
                order = 2

            remaining = bucket.get("remaining_fraction")
            if (
                isinstance(remaining, (int, float))
                and not isinstance(remaining, bool)
                and math.isfinite(remaining)
            ):
                percent = max(0.0, min(100.0, (1.0 - float(remaining)) * 100.0))
            else:
                percent = None

            resets_at = _parse_reset_at(bucket.get("reset_time"))
            reset_label: str | None = None
            note = bucket.get("description") if isinstance(bucket.get("description"), str) else None
            if percent == 0.0:
                resets_at = None
                reset_label = "idle"
            elif resets_at is not None and window_hours is not None:
                if resets_at - datetime.now() > timedelta(hours=window_hours) and percent == 0:
                    resets_at = None
                    reset_label = "idle"

            group_metrics.append(
                (
                    order,
                    UsageMetric(
                        label=window_text or group_label,
                        percent_used=percent,
                        resets_at=resets_at,
                        reset_label=reset_label,
                        note=note,
                        window_hours=window_hours,
                        group=group_label,
                    ),
                )
            )
        metrics.extend(m for _, m in sorted(group_metrics, key=lambda item: item[0]))

    return UsageSnapshot(
        provider="antigravity",
        display_name="Antigravity",
        status=SnapshotStatus.OK,
        metrics=metrics,
    )


class AntigravityProvider(Provider):
    id = "antigravity"
    display_name = "Antigravity"
    short_label = "AG"
    kind = "cli"

    def __init__(
        self,
        *,
        cli_path: str | None = None,
        show_gemini: bool = True,
        show_third_party: bool = True,
    ) -> None:
        self.cli_path = cli_path
        self.show_gemini = show_gemini
        self.show_third_party = show_third_party

    def fetch(self) -> UsageSnapshot:
        global _PROCESS_LATCHED_ERROR
        if _PROCESS_LATCHED_ERROR:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=_PROCESS_LATCHED_ERROR,
            )

        configured = normalize_cli_path(self.cli_path)
        if configured and not Path(configured).is_file():
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=f"agy CLI not found at {configured}",
            )
        if configured and not is_agy_file_name(configured):
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=f"Configured file is not named agy: {configured}",
            )

        exe = resolve_cli(configured)
        if not exe:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error="agy CLI not found (install Antigravity CLI or set path in Settings)",
            )

        try:
            proc = invoke_agy_cli(exe)
        except subprocess.TimeoutExpired:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=f"agy timeout after {_CLI_TIMEOUT_SECONDS}s",
            )
        except OSError as exc:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=f"Failed to start agy: {exc}",
            )

        try:
            payload = decode_agy_output(proc.stdout)
            return build_antigravity_snapshot(
                payload,
                show_gemini=self.show_gemini,
                show_third_party=self.show_third_party,
            )
        except RuntimeError as exc:
            _PROCESS_LATCHED_ERROR = str(exc)[:240]
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=_PROCESS_LATCHED_ERROR,
            )
        except (TypeError, ValueError) as exc:
            return UsageSnapshot(
                provider=self.id,
                display_name=self.display_name,
                status=SnapshotStatus.ERROR,
                error=str(exc)[:240],
            )
