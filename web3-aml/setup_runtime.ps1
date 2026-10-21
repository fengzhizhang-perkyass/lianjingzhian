$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runtimePython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtimePython)) {
    python -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 and retry.' }
}
& $runtimePython -m pip install -r (Join-Path $projectRoot 'requirements-web.txt')
if ($LASTEXITCODE -ne 0) { throw 'Runtime dependency installation failed.' }
Write-Host 'Ready. Run: .\run_web.ps1'
