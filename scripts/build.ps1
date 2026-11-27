<#
Build a standalone lightweight Windows binary (`dist\maew-usage\maew-usage.exe`)
and optionally package a Windows Installer (`-Installer`) using Inno Setup 6.
Uses Windows built-in Edge WebView2 (no bundled Chromium runtime).
#>
param(
    [switch]$Installer,
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPy = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Error "Virtualenv not found at .venv. Run: python -m venv .venv; .\.venv\Scripts\pip install -e .[dev]"
}

if (-not $Version) {
    $initPy = Get-Content (Join-Path $repoRoot "src\maew\__init__.py") -Raw
    if ($initPy -match '__version__\s*=\s*"([^"]+)"') {
        $Version = $Matches[1]
    } else {
        $Version = "1.0.0"
    }
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

    if ($Installer) {
        $iscc = (Get-Command iscc -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
        if (-not $iscc) {
            $defaultIscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
            if (Test-Path $defaultIscc) { $iscc = $defaultIscc }
        }
        if (-not $iscc) {
            Write-Error "Inno Setup 6 (ISCC.exe) not found. Install via: winget install JRSoftware.InnoSetup"
        }
        & $iscc "/DAppVersion=$Version" (Join-Path $repoRoot "scripts\installer.iss")
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Inno Setup compiler failed with exit code $LASTEXITCODE"
        }
        Write-Host "Installer complete -> dist\maew-usage-v$Version-windows-x64-setup.exe" -ForegroundColor Green
    }
} finally {
    Pop-Location
}

Write-Host "Build complete -> dist\maew-usage\maew-usage.exe" -ForegroundColor Green
