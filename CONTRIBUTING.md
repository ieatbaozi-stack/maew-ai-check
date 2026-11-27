# Contributing to maew usage

Contributions are welcome — especially new provider adapters, DOM extractor fixes when upstream usage pages change, and bug fixes.

## Development Setup (Windows)

Requirements: **Windows 10/11** (with Edge WebView2 Runtime, pre-installed on Windows 11) and **Python 3.11+**.

```powershell
git clone https://github.com/ieatbaozi-stack/maew-ai-check.git
cd maew-ai-check
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Run tests and JS syntax checks:

```powershell
.\.venv\Scripts\pytest.exe -v
node --check src/maew/frontend/cat-sprites.js
node --check src/maew/frontend/app.js
```

Run the app locally:

```powershell
.\.venv\Scripts\python.exe run.py
```

## Adding a New Provider

`maew usage` uses a minimal pluggable `Provider` interface so adding a new AI tool takes 4 small edits:

1. **Create `src/maew/providers/<name>.py`** subclassing `Provider` from `src/maew/providers/base.py`:
   - Set `id`, `display_name`, `short_label` (2 chars for Compact mode), and `kind` (`"cli"`, `"api_key"`, `"web"`, or `"local_logs"`).
   - Return a `UsageSnapshot` using standardized window labels (`5h`, `7d`, `24h`, `30d`) so weekly-cap lock indicators and compact mode work automatically.
   - Never log API keys, tokens, or cookies; disable redirects (`allow_redirects=False`) on authenticated requests when appropriate.
2. **Wire config & secrets** in `src/maew/config.py`, `src/maew/app.py`, and `src/maew/scanner.py` (keep new providers disabled by default).
3. **Register in the Settings catalog** (`PROVIDER_CATALOG` and `COMPACT_ORDER` in `src/maew/frontend/app.js`).
4. **Add unit tests** in `tests/` covering normal responses, auth errors, and edge cases — do not require live credentials in tests.

## Pull Request Checklist

- [ ] All tests pass (`pytest -v`).
- [ ] No telemetry, external CDN assets, or plaintext credentials added.
- [ ] UI changes preserve clean English copy, authored SVGs (no Unicode icon glyphs), and accessible contrast (`>= 4.5:1`).
- [ ] `README.md` or `SECURITY.md` updated if a new outbound domain or dependency is introduced.
