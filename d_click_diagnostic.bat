@echo off
REM D-button position diagnostic — no Python required.
REM Captures cursor position after a countdown so we can compare it
REM to TravelportAuto's computed click coordinates.
REM
REM Usage:
REM   1. Open Smartpoint, pull up an FS pricing screen (BOOK / +TQ rows visible)
REM   2. Double-click this file
REM   3. Move cursor to the actual D button BEFORE the countdown reaches 0

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "Add-Type -AssemblyName System.Windows.Forms;" ^
    "Write-Host '======================================================';" ^
    "Write-Host ' D-button position diagnostic';" ^
    "Write-Host '======================================================';" ^
    "Write-Host '';" ^
    "Write-Host 'Hover the mouse over the actual D button on screen';" ^
    "Write-Host 'BEFORE the countdown reaches 0:';" ^
    "Write-Host '';" ^
    "for ($i=8; $i -ge 1; $i--) { Write-Host (\"  $i...\"); Start-Sleep -Seconds 1 };" ^
    "$p = [System.Windows.Forms.Cursor]::Position;" ^
    "Write-Host '';" ^
    "Write-Host '======================================================';" ^
    "Write-Host (\"Actual D position    : ($($p.X), $($p.Y))\");" ^
    "Write-Host 'TravelportAuto tried : (1752, 248)';" ^
    "Write-Host (\"X offset (actual - tried): $($p.X - 1752) px\");" ^
    "Write-Host (\"Y offset (actual - tried): $($p.Y - 248) px\");" ^
    "Write-Host '======================================================';" ^
    "Write-Host '';" ^
    "Write-Host 'Send these numbers back to the developer.';"

echo.
pause
