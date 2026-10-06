param(
    # Rebuild with build_app.ps1 before launching.
    [switch]$Build
)

# Launch the locally built TravelportAuto.exe (dist\TravelportAuto).
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$exeDir = Join-Path $repoRoot "dist\TravelportAuto"
$exe = Join-Path $exeDir "TravelportAuto.exe"

if ($Build) {
    # Run in a child process: build_app.ps1 sets ErrorActionPreference=Stop and
    # pip's stderr notices would otherwise abort it under Windows PowerShell 5.1.
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "build_app.ps1")
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Build failed (exit $LASTEXITCODE); not launching."
        exit $LASTEXITCODE
    }
}

if (-not (Test-Path $exe)) {
    Write-Error "No build found at '$exe'. Run '.\launch.ps1 -Build' (or '.\build_app.ps1') first."
    exit 1
}

# Working directory matters: the exe reads commands.txt, preferences.json and
# data\ relative to its own folder.
$process = Start-Process -FilePath $exe -WorkingDirectory $exeDir -PassThru
$version = (Get-Item $exe).LastWriteTime.ToString("yyyy-MM-dd HH:mm")
Write-Host "Launched TravelportAuto (PID $($process.Id), built $version)."
