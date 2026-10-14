param([int]$MaxNodes = 0, [int]$Epochs = 0, [switch]$SkipDownload)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$taskPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskPython = Join-Path (Split-Path $projectRoot -Parent) '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run setup.ps1 first.' }
function Invoke-ProjectPython {
    param([string[]]$Arguments)
    & $taskPython @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Stage failed: python $($Arguments -join ' ')" }
}
Push-Location -LiteralPath $projectRoot
try {
    if (-not $SkipDownload) { Invoke-ProjectPython -Arguments @('scripts/00_download_data.py') }
    Invoke-ProjectPython -Arguments @('scripts/01_inspect_data.py')
    $dataArguments = @('scripts/02_preprocess.py')
    if ($MaxNodes -gt 0) { $dataArguments += @('--max-nodes', "$MaxNodes") }
    Invoke-ProjectPython -Arguments $dataArguments
    Invoke-ProjectPython -Arguments @('-m','pytest','tests/test_preprocess.py','-q')
    Invoke-ProjectPython -Arguments @('scripts/03_train_baseline.py')
    $modelArguments = @('scripts/04_train_dual_view.py')
    if ($Epochs -gt 0) { $modelArguments += @('--epochs', "$Epochs") }
    Invoke-ProjectPython -Arguments $modelArguments
    Invoke-ProjectPython -Arguments @('-m','pytest','tests/test_model.py','-q')
    Invoke-ProjectPython -Arguments @('scripts/05_evaluate.py')
    Invoke-ProjectPython -Arguments @('scripts/06_precompute_scores.py')
    Invoke-ProjectPython -Arguments @('-m','pytest','tests/test_graph_evidence.py','tests/test_tracing.py','tests/test_evidence_builder.py','-q')
    Invoke-ProjectPython -Arguments @('scripts/07_build_demo_cases.py')
    Invoke-ProjectPython -Arguments @('scripts/08_validate_demo.py')
    Invoke-ProjectPython -Arguments @('-m','pytest','-q')
    Write-Host 'Base pipeline passed. Launch run_demo.ps1. Investigation overlay is prepared separately by scripts 13-15.'
} finally { Pop-Location }
