# Changelog

All notable changes to `maew usage` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
