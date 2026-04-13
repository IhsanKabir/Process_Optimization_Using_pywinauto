# Build script for packaging the TravelportAuto GUI into an executable

# Activate the project's virtual environment if it exists
$venvActivate = Join-Path $PSScriptRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $venvActivate) {
    Write-Host "Activating virtual environment..."
    & $venvActivate
} else {
    Write-Host "[WARNING] No .venv found — installing into global Python."
}

Write-Host "Installing PyInstaller if needed..."
pip install pyinstaller

Write-Host "Building TravelportAuto.exe from TravelportAuto.spec..."
pyinstaller --clean TravelportAuto.spec

Write-Host ""
Write-Host "=========================================="
Write-Host "Build complete! Please find your executable here:"
Write-Host "dist\TravelportAuto.exe"
Write-Host "=========================================="
Write-Host ""
Write-Host "Notes:"
Write-Host "  - The packaged app includes the default config from the repo."
Write-Host "  - If commands.txt is missing on a user's machine, the app creates"
Write-Host "    a starter file automatically on first run."
