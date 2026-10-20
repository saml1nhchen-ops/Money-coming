$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$pythonBinary = $env:SIGNAL_PYTHON
if (-not $pythonBinary) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    if (Test-Path -LiteralPath $bundledPython) { $pythonBinary = $bundledPython }
    else { $pythonBinary = (Get-Command python -ErrorAction Stop).Source }
}
Set-Location -LiteralPath $taskRoot
Write-Host 'Signal GEO local tools: http://127.0.0.1:8770/#/w/demo/tools'
Write-Host 'Keep this process running while executing tools. Ctrl+C stops it.'
& $pythonBinary (Join-Path $taskRoot 'tools/native_service.py')
