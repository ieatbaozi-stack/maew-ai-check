# Changelog

All notable changes to `maew usage` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.1] - 2026-11-28

### Added
- **Auto-wake refresh on return from idle or sleep**: uses Windows `GetLastInputInfo` (read-only idle timer — never hooks or logs input) plus sleep/hibernate wall-clock detection to automatically refresh quotas and resume the active 5-minute polling cadence when you return after ≥5 minutes away or wake your PC, with a 60-second anti-spam cooldown.
- **Auto-refresh when reopening from System Tray**: showing a hidden widget after ≥1 minute triggers a fresh quota check automatically.

## [1.0.0] - 2026-11-27

### Added
- **Lightweight Windows desktop widget** built on Edge WebView2 (`pywebview`) + System Tray (`pystray`) — no bundled Chromium binary.
- **8-bit chubby cat companion** with 5 lineless pixel skins (`Ginger`, `Taupe`, `Shadow`, `Mochi`, `Cocoa`), 4 status-driven poses (sleeping loaf with floating `Z`, happy `^ ^`, watching/blinking, sweating at limit), and clickable petting hearts.
- **7 built-in AI quota providers** with a pluggable `Provider` registry:
  - **Claude** (`claude.ai` isolated WebView2 `5h` / `7d` gauges + collapsible offline `~/.claude/projects` local token/cost drawer).
  - **Antigravity** (local `agy --print /quota` CLI with zero-token Safety Latch and process-tree timeout guard).
  - **Codex** (`chatgpt.com` isolated WebView2 `5h` / `7d` gauges with label-free `<progress>` fallback).
  - **GitHub Copilot** (GitHub Billing REST API supporting AI Credits and legacy Premium Requests).
  - **OpenRouter** (`/api/v1/key` & `/credits` with optional daily budget).
  - **OpenCode Go** (`/zen/go/v1/usage` `5h` / `7d` / `30d` windows).
  - **MiniMax Coding Plan** (International & China endpoints with `allow_redirects=False` key protection).
- **Weekly-cap lock indicator**: automatically marks `5h` rows as `Paused · 7d full` (with padlock icon and red status dot) when a group's `7d` quota hits 100%, in both Expanded and Compact modes.
- **Standardized Compact Mode**: always displays `5h` session percentage per provider (plus red padlock when `7d` is capped) without wrapping the top bar.
- **Local Harness Auto-Scanner**: offline read-only scan button in Settings to detect installed CLIs, log folders, and saved keys.
- **Adaptive Polling Scheduler**: 5-minute active cadence with exponential idle backoff up to 60 minutes and automatic pull-forward 1 minute after predicted quota resets.
- **Windows DPAPI encrypted secret storage** (`crypt32.dll`) and self-hosted offline fonts (`IBM Plex Sans` + `JetBrains Mono`).
- **Windows distribution**: per-user Inno Setup installer (`-setup.exe` with Start Menu & optional Windows startup), portable `.zip` with `.NET` `loadFromRemoteSources` config, Scoop bucket manifest (`bucket/maew-usage.json`), and windowless `uv`/`pipx` GUI entry point.
