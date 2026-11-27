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
        --noupx `
        --windowed `
        --name "maew-usage" `
        --icon "src\maew\assets\maew-usage.ico" `
        --paths "src" `
        --add-data "src\maew\frontend;maew\frontend" `
        --add-data "src\maew\assets;maew\assets" `
        --add-data "src\maew\providers\rates.json;maew\providers" `
        run.py

    # Required so .NET Framework (pythonnet / pywebview) can load bundled
    # managed assemblies when users extract a downloaded .zip from GitHub
    # Releases (Windows Explorer marks extracted files with Mark of the Web).
    $appConfig = @"
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <runtime>
    <loadFromRemoteSources enabled="true"/>
  </runtime>
</configuration>
"@
    $configOut = Join-Path $repoRoot "dist\maew-usage\maew-usage.exe.config"
    [System.IO.File]::WriteAllText($configOut, $appConfig, [System.Text.UTF8Encoding]::new($false))
} finally {
    Pop-Location
}

Write-Host "Build complete -> dist\maew-usage\maew-usage.exe" -ForegroundColor Green
