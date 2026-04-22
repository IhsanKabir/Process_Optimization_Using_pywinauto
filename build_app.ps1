param(
    [ValidateSet("onedir", "onefile")]
    [string]$Mode = "onedir"
)

# Build script for packaging the TravelportAuto GUI into an executable.
# Default mode is onedir because it starts faster and avoids PyInstaller's
# one-file _MEI extraction work on every launch.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $python) {
    Write-Host "Using virtual environment Python..."
} else {
    Write-Host "[WARNING] No .venv found - using global Python."
    $python = "python"
}

Write-Host "Installing PyInstaller if needed..."
& $python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Installing application requirements..."
& $python -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Old one-file builds extract into dist\_MEI* because the previous spec used
# runtime_tmpdir='.'. Remove stale extraction folders before building/running.
$distDir = Join-Path $PSScriptRoot "dist"
if (Test-Path $distDir) {
    foreach ($meiDir in Get-ChildItem -Path $distDir -Directory -Filter "_MEI*" -ErrorAction SilentlyContinue) {
        try {
            Remove-Item -LiteralPath $meiDir.FullName -Recurse -Force -ErrorAction Stop
        } catch {
            Write-Warning "Could not remove stale extraction folder '$($meiDir.FullName)'. Close any running TravelportAuto.exe and delete it later."
        }
    }
}

if ($Mode -eq "onedir") {
    $targetExe = Join-Path $distDir "TravelportAuto\TravelportAuto.exe"
} else {
    $targetExe = Join-Path $distDir "TravelportAuto.exe"
}

if (Test-Path $targetExe) {
    try {
        $lockCheck = [System.IO.File]::Open(
            $targetExe,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        $lockCheck.Dispose()
    } catch {
        Write-Error "Cannot replace '$targetExe'. Close any running TravelportAuto.exe from that path, then run the build again."
        exit 1
    }
}

$runtimeBackupRoot = $null
if ($Mode -eq "onedir") {
    $runtimeRoot = Join-Path $distDir "TravelportAuto"
    $runtimeItems = @(
        "data",
        "commands.txt",
        "preferences.json",
        "_tpa_update_state.txt",
        "_tpa_update.log"
    )

    if (Test-Path $runtimeRoot) {
        foreach ($item in $runtimeItems) {
            $sourcePath = Join-Path $runtimeRoot $item
            if (-not (Test-Path $sourcePath)) {
                continue
            }
            if (-not $runtimeBackupRoot) {
                $runtimeBackupRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("TravelportAuto_build_backup_" + [guid]::NewGuid())
                New-Item -ItemType Directory -Path $runtimeBackupRoot -Force | Out-Null
            }
            Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $runtimeBackupRoot $item) -Recurse -Force
        }
    }
}

Write-Host "Building TravelportAuto.exe from TravelportAuto.spec ($Mode mode)..."
$env:TPA_PYINSTALLER_MODE = $Mode
$buildExitCode = 0
try {
    & $python -m PyInstaller --noconfirm --clean TravelportAuto.spec
    $buildExitCode = $LASTEXITCODE
} finally {
    Remove-Item Env:\TPA_PYINSTALLER_MODE -ErrorAction SilentlyContinue
}

if ($Mode -eq "onedir" -and $runtimeBackupRoot -and (Test-Path $runtimeBackupRoot)) {
    $runtimeRoot = Join-Path $distDir "TravelportAuto"
    if (Test-Path $runtimeRoot) {
        Copy-Item -Path (Join-Path $runtimeBackupRoot "*") -Destination $runtimeRoot -Recurse -Force
    } else {
        Write-Warning "Build output folder '$runtimeRoot' was not created; runtime backup left at '$runtimeBackupRoot'."
    }
    Remove-Item -LiteralPath $runtimeBackupRoot -Recurse -Force -ErrorAction SilentlyContinue
}

if ($buildExitCode -ne 0) { exit $buildExitCode }

Write-Host ""
Write-Host "=========================================="
Write-Host "Build complete! Please find your executable here:"
Write-Host $targetExe.Replace($PSScriptRoot + "\", "")
Write-Host "=========================================="
Write-Host ""
Write-Host "Notes:"
Write-Host "  - The packaged app includes the default config from the repo."
Write-Host "  - If commands.txt is missing, the app creates a starter file on first run."
if ($Mode -eq "onedir") {
    Write-Host "  - Copy/run the whole dist\TravelportAuto folder for best performance."
    Write-Host "  - Use .\build_app.ps1 -Mode onefile only when you need a single exe."
} else {
    Write-Host "  - One-file builds are easier to share but slower to start because they extract on launch."
}
