$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$taskPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    $localPackages = Join-Path $projectRoot '..\..\work\python-packages'
    if ((Test-Path -LiteralPath $bundledPython) -and (Test-Path -LiteralPath $localPackages)) {
        $taskPython = $bundledPython
        $env:PYTHONPATH = (Resolve-Path -LiteralPath $localPackages).Path
    } else { $taskPython = 'python' }
}
& $taskPython -m streamlit run app.py --server.address 127.0.0.1
