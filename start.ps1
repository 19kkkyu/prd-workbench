$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    $localPackages = Join-Path $PSScriptRoot '..\..\work\python-packages'
    if ((Test-Path -LiteralPath $bundledPython) -and (Test-Path -LiteralPath $localPackages)) {
        $taskPython = $bundledPython
        $env:PYTHONPATH = (Resolve-Path -LiteralPath $localPackages).Path
    } else {
        $taskPython = 'python'
    }
}
& $taskPython -m streamlit run app.py --server.address 127.0.0.1
