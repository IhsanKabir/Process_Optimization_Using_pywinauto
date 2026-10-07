param(
    # Release version, e.g. v1.5.31. Must match VERSION in gui.py.
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^v\d+\.\d+\.\d+$')]
    [string]$Version
)

# Zip the built app for a GitHub release. Only the files meant to ship are
# included: build_app.ps1 restores runtime files (data\ with logs, scrapes and
# reports; _tpa_update.log) into dist\TravelportAuto, and those must never be
# published.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$buildDir = Join-Path $repoRoot "dist\TravelportAuto"
$zipPath = Join-Path $repoRoot "dist\TravelportAuto-$Version-windows.zip"

$shipItems = @(
    "TravelportAuto.exe",
    "_internal",
    "agent_config.json",
    "commands.txt",
    "preferences.json"
)

$guiVersion = Select-String -Path (Join-Path $repoRoot "gui.py") -Pattern 'VERSION\s*=\s*"(v[^"]+)"' |
    Select-Object -First 1 | ForEach-Object { $_.Matches[0].Groups[1].Value }
if ($guiVersion -ne $Version) {
    Write-Error "gui.py VERSION is '$guiVersion' but you asked for '$Version'. Bump gui.py, rebuild, then package."
    exit 1
}

$exe = Join-Path $buildDir "TravelportAuto.exe"
if (-not (Test-Path $exe)) {
    Write-Error "No build at '$exe'. Run .\build_app.ps1 first."
    exit 1
}
$guiStamp = (Get-Item (Join-Path $repoRoot "gui.py")).LastWriteTime
if ((Get-Item $exe).LastWriteTime -lt $guiStamp) {
    Write-Error "The exe is older than gui.py; rebuild with .\build_app.ps1 so the version matches."
    exit 1
}

# A running copy of this build locks its files (same check as build_app.ps1;
# comparing process paths misses folders reached through another drive path).
try {
    $lockCheck = [System.IO.File]::Open(
        $exe,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
    $lockCheck.Dispose()
} catch {
    Write-Error "'$exe' is in use. Close the TravelportAuto.exe running from dist\TravelportAuto, then package."
    exit 1
}

$missing = $shipItems | Where-Object { -not (Test-Path (Join-Path $buildDir $_)) }
if ($missing) {
    Write-Error "Build output is missing: $($missing -join ', ')"
    exit 1
}

$paths = $shipItems | ForEach-Object { Join-Path $buildDir $_ }
Compress-Archive -Path $paths -DestinationPath $zipPath -Force

# Verify nothing from the runtime folder slipped in.
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    $leaked = $zip.Entries | Where-Object { $_.FullName -match '^(data[\\/]|_tpa_update)' }
} finally {
    $zip.Dispose()
}
if ($leaked) {
    Remove-Item $zipPath -Force
    Write-Error "Runtime files found in the zip; aborted: $($leaked.FullName -join ', ')"
    exit 1
}

$sizeMb = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
Write-Host "Packaged $zipPath ($sizeMb MB)."
Write-Host "Publish with:"
Write-Host "  gh release create $Version `"$zipPath`" --title `"$Version - <summary>`" --notes `"<notes>`""
