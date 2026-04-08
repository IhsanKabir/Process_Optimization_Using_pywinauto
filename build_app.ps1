# Build script for packaging the Travelport Automation script into an executable

Write-Host "Installing PyInstaller if needed..."
pip install pyinstaller

Write-Host "Re-building the Python script into a standalone .exe..."

# Run PyInstaller
# --onefile packages everything into a single .exe
# --clean removes cached builds
# --name sets the final output filename
# --icon can be used later if you have an .ico file
pyinstaller --clean --onefile --name "TravelportAuto" main.py

Write-Host ""
Write-Host "=========================================="
Write-Host "Build complete! Please find your executable here:"
Write-Host "dist\TravelportAuto.exe"
Write-Host "=========================================="
Write-Host ""
Write-Host "To distribute this to your clients, zip the 'dist\TravelportAuto.exe' file"
Write-Host "along with your 'config.json' and 'commands.txt' template files."
