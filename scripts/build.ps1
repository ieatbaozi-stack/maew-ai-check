<#
Build a standalone lightweight Windows binary (`dist\maew-usage\maew-usage.exe`).
Uses Windows built-in Edge WebView2 (no bundled Chromium runtime).
#>
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Error "Virtualenv not found at .venv. Run: python -m venv .venv; .\.venv\Scripts\pip install -e .[dev]"
}

Push-Location $repoRoot
try {
    & $venvPy -m pip install --quiet pyinstaller
    & $venvPy -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --name "maew-usage" `
        --paths "src" `
        --add-data "src\maew\frontend;maew\frontend" `
        --add-data "src\maew\providers\rates.json;maew\providers" `
        run.py
} finally {
    Pop-Location
}

Write-Host "Build complete -> dist\maew-usage\maew-usage.exe" -ForegroundColor Green
