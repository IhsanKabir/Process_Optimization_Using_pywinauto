# Build script for packaging the Travelport Automation script into an executable

Write-Host "Installing PyInstaller if needed..."
pip install pyinstaller

Write-Host "Re-building the Python script into a standalone agent .exe..."

# Run PyInstaller
# --onefile packages everything into a single .exe
# --clean removes cached builds
# --name sets the final output filename
# --icon can be used later if you have an .ico file
pyinstaller --clean --onefile --name "TravelportAgent" main.py

Write-Host ""
Write-Host "=========================================="
Write-Host "Build complete! Please find your executable here:"
Write-Host "dist\TravelportAgent.exe"
Write-Host "=========================================="
Write-Host ""
Write-Host "To distribute this to your users, zip the 'dist\TravelportAgent.exe' file"
Write-Host "along with:"
Write-Host "  - config.json"
Write-Host "  - commands.txt"
Write-Host "  - agent_config.json.example"
