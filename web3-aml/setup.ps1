param([ValidateSet('cpu','cu121')][string]$TorchBuild = 'cpu')
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$localPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$parentPython = Join-Path (Split-Path $projectRoot -Parent) '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $localPython) { $taskPython = $localPython }
elseif (Test-Path -LiteralPath $parentPython) { $taskPython = $parentPython }
else {
    python -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create Python venv' }
    $taskPython = $localPython
}
& $taskPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed' }
& $taskPython -m pip install "torch==2.5.1+$TorchBuild" --no-deps --index-url "https://download.pytorch.org/whl/$TorchBuild"
if ($LASTEXITCODE -ne 0) { throw 'PyTorch installation failed' }
& $taskPython -m pip install -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& $taskPython -m pip install "pyg_lib==0.4.0+pt25$TorchBuild" --no-index -f "https://data.pyg.org/whl/torch-2.5.1+$TorchBuild.html"
if ($LASTEXITCODE -ne 0) { throw 'NeighborLoader backend installation failed' }
Write-Host "Ready. Python: $taskPython"
