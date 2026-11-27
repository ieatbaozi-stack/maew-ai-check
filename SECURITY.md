# Security Policy

`maew usage` handles session cookies and API keys on your local machine. This document describes its exact security model, outbound network surface, and how to report vulnerabilities.

## Security Model & Guarantees

1. **Zero Telemetry & Zero Auto-Updater**
   - `maew usage` never contacts any analytics, crash-reporting, update-checking, or third-party server.
   - Fonts (`IBM Plex Sans`, `JetBrains Mono`) are self-hosted locally inside `src/maew/frontend/fonts/`.

2. **Outbound Network Surface (Complete Allowlist)**
   The application only communicates with the official endpoints of providers you explicitly enable:
   - **Claude.ai**: `https://claude.ai/login`, `https://claude.ai/settings/usage` (isolated WebView2)
   - **Codex (ChatGPT)**: `https://chatgpt.com/auth/login`, `https://chatgpt.com/settings/usage?tab=overview` (isolated WebView2)
   - **GitHub Copilot**: `https://api.github.com/user`, `/users/{user}/settings/billing/...`, `/organizations/{org}/settings/billing/...` (HTTP 3xx redirects refused)
   - **OpenRouter**: `https://openrouter.ai/api/v1/key`, `/credits` (HTTP 3xx redirects refused)
   - **OpenCode Go**: `https://opencode.ai/zen/go/v1/usage` (HTTP 3xx redirects refused)
   - **MiniMax**: `https://api.minimax.io/v1/token_plan/remains` or `https://api.minimax.cn/v1/token_plan/remains` (strictly per selected region; HTTP 3xx redirects refused)
   - **Antigravity**: No direct network calls from Python; invokes local `agy --print /quota --output-format json --mode plan --sandbox --print-timeout 30s` with `AGY_CLI_DISABLE_AUTO_UPDATE=true`
   - **Claude Code Local Logs**: 100% offline; reads only `message.usage` token counters from `~/.claude/projects/**/*.jsonl` (never reads prompt text or tool outputs)

3. **Credential & Browser Profile Isolation**
   - **Never touches your main browser profile.** Web sign-ins (`claude.ai`, `chatgpt.com`) use an isolated Edge WebView2 profile stored at `%APPDATA%\maew-ai-check\webview2`.
   - **Encrypted secret storage.** API keys and PATs are encrypted with **Windows DPAPI** (`crypt32.dll` `CryptProtectData` with application entropy) and stored in `%APPDATA%\maew-ai-check\secrets.dat`. They are never written to `config.json` or log files.
   - **Non-Windows fail-closed guard.** Writing secrets on non-Windows hosts raises `RuntimeError` unless explicitly opted into for development tests via `MAEW_ALLOW_PLAINTEXT_SECRETS=1`.

4. **Subprocess & Quota Protection**
   - Every subprocess uses an explicit argument list (`shell=False`), `stdin=DEVNULL`, `CREATE_NO_WINDOW`, a fresh empty temporary working directory, and a 60-second hard timeout with process-tree cleanup (`taskkill.exe /T /F`).
   - **Antigravity Safety Latch:** If `agy --print /quota` ever returns `num_turns > 0` or `usage.total_tokens > 0`, polling latches closed for the remainder of the process so a broken CLI update cannot silently spend model quota.

## Known Threat Model Boundaries

- Windows DPAPI binds encryption to the current Windows user account. It protects secrets against offline theft or access by other Windows users on the same machine, but any malicious process running under your own Windows user session can access your DPAPI context (the standard desktop application threat model).
- Unsigned PyInstaller executables built locally may trigger Windows Defender SmartScreen warnings. Users can audit the source and run directly via Python (`pythonw run.py`) or build locally with `build.ps1`.

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities. Instead, use GitHub's **Private Vulnerability Reporting** ("Report a vulnerability" under the Security tab) with:

1. A clear description of the issue and affected file/lines.
2. Steps to reproduce or proof of concept.
3. Suggested mitigation (if you have one).
