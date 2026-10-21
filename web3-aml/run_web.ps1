param(
    [int]$Port = 8000,
    [string]$PythonPath = ''
)
$ErrorActionPreference = 'Stop'
if (-not $PythonPath) {
    foreach ($candidate in @(
        (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
        (Join-Path (Split-Path $PSScriptRoot -Parent) '.venv\Scripts\python.exe')
    )) {
        if (Test-Path -LiteralPath $candidate) { $PythonPath = $candidate; break }
    }
}
if (-not $PythonPath) { $PythonPath = 'python' }
Push-Location -LiteralPath $PSScriptRoot
try {
    & $PythonPath run_web.py --port $Port
    if ($LASTEXITCODE -ne 0) { throw 'Startup failed. Install requirements-web.txt and check runtime data.' }
} finally { Pop-Location }
