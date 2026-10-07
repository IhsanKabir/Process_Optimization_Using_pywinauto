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

# PyInstaller replaces dist\TravelportAuto and the runtime restore below
# overwrites files in it, so any file held open (a report in Excel, a log in an
# editor) breaks the build halfway. Fail up front and name the files instead.
if ($Mode -eq "onedir") {
    $outputRoot = Join-Path $distDir "TravelportAuto"
    if (Test-Path $outputRoot) {
        $lockedFiles = foreach ($file in Get-ChildItem -LiteralPath $outputRoot -Recurse -File -ErrorAction SilentlyContinue) {
            try {
                $handle = [System.IO.File]::Open(
                    $file.FullName,
                    [System.IO.FileMode]::Open,
                    [System.IO.FileAccess]::ReadWrite,
                    [System.IO.FileShare]::None
                )
                $handle.Dispose()
            } catch {
                $file.FullName.Substring($outputRoot.Length + 1)
            }
        }
        if ($lockedFiles) {
            $shown = ($lockedFiles | Select-Object -First 10) -join "`n  "
            Write-Error ("These files in dist\TravelportAuto are open in another program " +
                "(close them, e.g. the report in Excel, then build again):`n  $shown")
            exit 1
        }
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
    $restored = $false
    if (Test-Path $runtimeRoot) {
        try {
            Copy-Item -Path (Join-Path $runtimeBackupRoot "*") -Destination $runtimeRoot -Recurse -Force -ErrorAction Stop
            $restored = $true
        } catch {
            Write-Warning "Could not restore your data into '$runtimeRoot': $($_.Exception.Message)"
        }
    } else {
        Write-Warning "Build output folder '$runtimeRoot' was not created."
    }
    if ($restored) {
        Remove-Item -LiteralPath $runtimeBackupRoot -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Write-Warning "Your data (reports, logs, settings) is kept at '$runtimeBackupRoot'; copy it back manually."
    }
}

if ($buildExitCode -ne 0) { exit $buildExitCode }

# Copy agent_config.json (secrets-free) into the output directory so the zip
# ships with it pre-populated. Only safe keys are written - the client secret
# is intentionally excluded because it now lives on the server.
$agentConfigSrc = Join-Path $PSScriptRoot "agent_config.json"
if (Test-Path $agentConfigSrc) {
    $srcJson = Get-Content $agentConfigSrc -Raw | ConvertFrom-Json
    $safeKeys = @("google_oauth_client_id", "api_base_url")
    $distJson = @{}
    foreach ($key in $safeKeys) {
        $val = $srcJson.$key
        if ($val) { $distJson[$key] = $val }
    }
    $distJsonText = $distJson | ConvertTo-Json -Depth 2

    if ($Mode -eq "onedir") {
        $agentConfigDst = Join-Path $distDir "TravelportAuto\agent_config.json"
    } else {
        $agentConfigDst = Join-Path $distDir "agent_config.json"
    }
    [System.IO.File]::WriteAllText($agentConfigDst, $distJsonText, [System.Text.UTF8Encoding]::new($false))
    Write-Host "  Copied agent_config.json to output folder (secrets excluded)."
} else {
    Write-Warning "  agent_config.json not found at repo root - skipping copy. Add it before zipping."
}

# Copy commands.txt and preferences.json so users have defaults out of the box.
$extras = @("commands.txt", "preferences.json")
foreach ($extra in $extras) {
    $src = Join-Path $PSScriptRoot $extra
    if (Test-Path $src) {
        $dst = if ($Mode -eq "onedir") { Join-Path $distDir "TravelportAuto\$extra" } else { Join-Path $distDir $extra }
        Copy-Item $src $dst -Force
        Write-Host "  Copied $extra to output folder."
    } else {
        Write-Warning "  $extra not found at repo root - skipping."
    }
}

Write-Host ""
Write-Host "=========================================="
Write-Host "Build complete! Please find your executable here:"
Write-Host $targetExe.Replace($PSScriptRoot + "\", "")
Write-Host "=========================================="
Write-Host ""
Write-Host "Notes:"
Write-Host "  - agent_config.json is included in the output folder automatically."
Write-Host "  - If commands.txt is missing, the app creates a starter file on first run."
if ($Mode -eq "onedir") {
    Write-Host "  - Copy/run the whole dist\TravelportAuto folder for best performance."
    Write-Host "  - Use .\build_app.ps1 -Mode onefile only when you need a single exe."
} else {
    Write-Host "  - One-file builds are easier to share but slower to start because they extract on launch."
}
