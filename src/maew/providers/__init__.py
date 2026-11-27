"""Pluggable provider registry for maew usage."""

from .antigravity import AntigravityProvider
from .base import Provider, ProviderRegistry
from .claude_logs import ClaudeCodeLocalProvider
from .claude_web import ClaudeWebProvider
from .codex import CodexProvider
from .copilot import CopilotProvider
from .minimax import MiniMaxProvider
from .opencode_go import OpenCodeGoProvider
from .openrouter import OpenRouterProvider

__all__ = [
    "AntigravityProvider",
    "ClaudeCodeLocalProvider",
    "ClaudeWebProvider",
    "CodexProvider",
    "CopilotProvider",
    "MiniMaxProvider",
    "OpenCodeGoProvider",
    "OpenRouterProvider",
    "Provider",
    "ProviderRegistry",
]
