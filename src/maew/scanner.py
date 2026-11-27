"""Offline read-only local harness & provider auto-scanner.

Detects which AI coding CLIs, log folders, or API key configurations exist on
this machine without executing any subprocesses or reading external credentials.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .providers.antigravity import resolve_cli as resolve_agy_cli
from .providers.claude_logs import default_claude_log_roots
from .secrets import SecretStore


def _has_vscode_copilot() -> bool:
    ext_dir = Path.home() / ".vscode" / "extensions"
    if not ext_dir.is_dir():
        return False
    try:
        return any(p.name.lower().startswith("github.copilot") for p in ext_dir.iterdir())
    except OSError:
        return False


def scan_local_harnesses(secrets: SecretStore | None = None) -> dict[str, dict[str, Any]]:
    """Return detection metadata for every supported provider id."""
    home = Path.home()
    results: dict[str, dict[str, Any]] = {}

    # 1. Antigravity (`agy` CLI)
    agy_exe = resolve_agy_cli()
    results["antigravity"] = {
        "detected": bool(agy_exe),
        "detail": "agy CLI installed" if agy_exe else "agy CLI not found",
        "kind": "cli",
    }

    # 2. Claude Code / Claude.ai
    claude_cli = shutil.which("claude")
    claude_logs = any(root.is_dir() for root in default_claude_log_roots())
    results["claude_web"] = {
        "detected": bool(claude_cli or claude_logs),
        "detail": "Claude Code detected" if (claude_cli or claude_logs) else "Web sign-in available",
        "kind": "web",
    }
    results["claude_code"] = {
        "detected": bool(claude_logs),
        "detail": "Local ~/.claude logs found" if claude_logs else "No local Claude logs yet",
        "kind": "local_logs",
    }

    # 3. Codex (OpenAI Codex CLI / ChatGPT)
    codex_cli = shutil.which("codex")
    codex_dir = (home / ".codex").is_dir()
    results["codex"] = {
        "detected": bool(codex_cli or codex_dir),
        "detail": "Codex CLI detected" if (codex_cli or codex_dir) else "Web sign-in available",
        "kind": "web",
    }

    # 4. GitHub Copilot
    gh_cli = shutil.which("gh")
    copilot_ext = _has_vscode_copilot()
    has_pat = bool(secrets and secrets.get("github_pat"))
    results["copilot"] = {
        "detected": bool(has_pat or copilot_ext or gh_cli),
        "detail": (
            "PAT saved"
            if has_pat
            else ("VS Code Copilot detected" if copilot_ext else ("GitHub CLI detected" if gh_cli else "Needs GitHub PAT"))
        ),
        "kind": "api_key",
        "has_key": has_pat,
    }

    # 5. OpenRouter
    has_or_key = bool(secrets and secrets.get("openrouter_key"))
    has_or_env = bool(os.environ.get("OPENROUTER_API_KEY"))
    results["openrouter"] = {
        "detected": bool(has_or_key or has_or_env),
        "detail": (
            "API key saved"
            if has_or_key
            else ("OPENROUTER_API_KEY env found" if has_or_env else "Needs API key")
        ),
        "kind": "api_key",
        "has_key": has_or_key,
    }

    # 6. OpenCode Go
    oc_cli = shutil.which("opencode")
    oc_dir = (home / ".config" / "opencode").is_dir()
    has_oc_key = bool(secrets and secrets.get("opencode_go_key"))
    results["opencode_go"] = {
        "detected": bool(has_oc_key or oc_cli or oc_dir),
        "detail": (
            "API key saved"
            if has_oc_key
            else ("OpenCode CLI detected" if (oc_cli or oc_dir) else "Needs OpenCode key")
        ),
        "kind": "api_key",
        "has_key": has_oc_key,
    }

    # 7. MiniMax Coding Plan
    has_mm_key = bool(secrets and secrets.get("minimax_key"))
    has_mm_env = bool(os.environ.get("MINIMAX_API_KEY"))
    results["minimax"] = {
        "detected": bool(has_mm_key or has_mm_env),
        "detail": (
            "API key saved"
            if has_mm_key
            else ("MINIMAX_API_KEY env found" if has_mm_env else "Needs Coding Plan key")
        ),
        "kind": "api_key",
        "has_key": has_mm_key,
    }

    return results
