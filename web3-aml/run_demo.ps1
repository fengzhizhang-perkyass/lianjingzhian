$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$taskPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskPython = Join-Path (Split-Path $projectRoot -Parent) '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run setup.ps1 first.' }
Push-Location -LiteralPath $projectRoot
try { & $taskPython -m streamlit run app.py } finally { Pop-Location }
