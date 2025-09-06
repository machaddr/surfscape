#!/usr/bin/env pwsh

# Build script for creating Windows installer for Surfscape (Static/Standalone Build)
# Mirrors the Debian build flow in build-deb.sh: clean, verify, build, package, and print install steps

param(
    [Parameter(Position=0)]
    [ValidateSet('clean')]
    [string]$Action
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Header($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Step($msg) { Write-Host "- $msg" -ForegroundColor DarkCyan }
function Try-Remove($path) { if (Test-Path $path) { Remove-Item -Recurse -Force $path -ErrorAction SilentlyContinue } }

function Clean-Windows {
    Write-Header "Performing comprehensive Windows clean"
    # PyInstaller / Python artifacts
    Write-Step "Removing Python build artifacts..."
    Try-Remove "build"
    Try-Remove "dist"
    Get-ChildItem -Path . -Recurse -Include "*.egg-info", ".pybuild", "__pycache__" -ErrorAction SilentlyContinue |
        ForEach-Object { Try-Remove $_.FullName }
    Get-ChildItem -Path . -Recurse -Include "*.pyc" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

    # Installer outputs
    Write-Step "Removing installer outputs..."
    Try-Remove "installer\Output"
    Try-Remove "installer\Build"
    Get-ChildItem -Path . -Recurse -Include "Surfscape-setup-*.exe", "surfscape-windows-portable.zip" -ErrorAction SilentlyContinue |
        ForEach-Object { Try-Remove $_.FullName }

    # Local venv (optional)
    Write-Step "Removing local virtual environment (.venv) if present..."
    Try-Remove ".venv"

    Write-Host "Clean complete!" -ForegroundColor Green
}

if ($Action -eq 'clean') {
    Clean-Windows
    exit 0
}

Write-Header "Building Windows package for Surfscape (Static Build)"

# Ensure we're in the project root
if (-not (Test-Path "surfscape.py")) {
    Write-Error "surfscape.py not found. Please run this script from the project root."
}

# Resolve Python
function Resolve-Python {
    $candidates = @('py -3', 'py', 'python3', 'python')
    foreach ($c in $candidates) {
        $parts = $c -split '\s+'
        $cmd = $parts[0]
        $args = @()
        if ($parts.Length -gt 1) { $args = $parts[1..($parts.Length-1)] }
        try {
            & $cmd @args --version *> $null
            if ($LASTEXITCODE -eq 0) { return @($cmd) + $args }
        } catch {}
    }
    throw 'Python not found. Install Python 3.8+ and ensure it is on PATH.'
}

$py = Resolve-Python
Write-Step ("Using Python command: " + ($py -join ' '))

# Clean previous builds
Clean-Windows

# Determine version from setup.py (fallback to 1.0)
$version = '1.0'
try {
    $setup = Get-Content -Raw -Path "setup.py"
    if ($setup -match 'version="([0-9]+\.[0-9]+\.[0-9]+)"') { $version = $Matches[1] }
} catch {}
Write-Step "Project version: $version"

# Create and use a local venv for reproducibility
Write-Step "Preparing Python virtual environment (.venv)"
& $py -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "Failed to create virtual environment" }

$venvPython = Join-Path -Path ".venv" -ChildPath "Scripts\python.exe"
if (-not (Test-Path $venvPython)) { $venvPython = Join-Path -Path ".venv" -ChildPath "bin/python" }
if (-not (Test-Path $venvPython)) { throw "Unable to locate venv python interpreter" }

Write-Step "Upgrading pip and installing requirements"
& $venvPython -m pip install --upgrade pip wheel setuptools
& $venvPython -m pip install -r requirements.txt

# Verify PyInstaller available
Write-Step "Verifying PyInstaller availability"
& $venvPython -m PyInstaller --version | Out-Null

# Build the standalone app using the provided spec
Write-Header "Building standalone executable with PyInstaller"
& $venvPython -m PyInstaller --noconfirm surfscape.spec

# Bundle docs and license with the app folder
Write-Step "Bundling documentation"
Copy-Item -Path "README.md" -Destination "dist/surfscape" -Force
Copy-Item -Path "LICENSE" -Destination "dist/surfscape" -Force

# Sanity check: ensure dist output exists
if (-not (Test-Path "dist/surfscape/surfscape.exe")) {
    if (-not (Test-Path "dist/surfscape")) {
        throw "PyInstaller output folder not found at dist/surfscape. Build likely failed earlier."
    } else {
        throw "PyInstaller executable not found at dist/surfscape/surfscape.exe. Verify surfscape.spec name and build logs."
    }
}

# Try to compile installer with Inno Setup (ISCC)
Write-Header "Packaging installer (Inno Setup)"

function Find-ISCC {
    # Common locations for ISCC.exe
    $candidates = @(
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    # Try via PATH
    $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue)?.Source
    if ($iscc) { return $iscc }
    return $null
}

$iscc = Find-ISCC
$issPath = Resolve-Path "installer/Surfscape.iss"
if (-not (Test-Path $issPath)) { throw "Missing installer/Surfscape.iss" }

New-Item -ItemType Directory -Path "installer/Output" -Force | Out-Null

if ($iscc) {
    Write-Step "Using ISCC at: $iscc"
    $distAbs = Resolve-Path "dist/surfscape"
    $outAbs = Resolve-Path "installer/Output"
    & $iscc "${issPath}" "/DVersion=$version" "/DDistDir=$distAbs" "/DOutputDir=$outAbs"
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed" }
    Write-Host "Installer created in installer/Output" -ForegroundColor Green
} else {
    Write-Step "Inno Setup not found. Creating portable ZIP instead."
    $zip = "surfscape-windows-portable.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path "dist/surfscape/*" -DestinationPath $zip
    Write-Host "Portable ZIP created: $zip" -ForegroundColor Green
}

Write-Host "`nBuild complete!" -ForegroundColor Green
Write-Host "Artifacts:" -ForegroundColor DarkGreen
Get-ChildItem -Path dist -Recurse | Where-Object { -not $_.PSIsContainer } | ForEach-Object { Write-Host "  dist/"$_.FullName.Substring((Resolve-Path dist).Path.Length+1) }
if (Test-Path "installer/Output") { Get-ChildItem "installer/Output" | ForEach-Object { Write-Host "  installer/Output/$($_.Name)" } }
if (Test-Path "surfscape-windows-portable.zip") { Write-Host "  surfscape-windows-portable.zip" }

Write-Host "`nTo install (with installer):" -ForegroundColor Cyan
Write-Host "- Run the generated Surfscape-setup-$version.exe in installer/Output"
Write-Host "`nTo uninstall:" -ForegroundColor Cyan
Write-Host "- Use Windows Apps & Features or the Uninstall shortcut created by the installer"
Write-Host "`nTo clean build artifacts:" -ForegroundColor Cyan
Write-Host ".\\build-windows.ps1 clean"
