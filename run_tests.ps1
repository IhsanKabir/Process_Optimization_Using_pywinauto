param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Error "Repo virtual environment not found at '$venvPython'. Create it with 'python -m venv .venv' and install dev dependencies with '.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt'."
    exit 1
}

Push-Location $repoRoot
try {
    & $venvPython -m pytest @PytestArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
