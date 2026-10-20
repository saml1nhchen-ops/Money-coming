$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = (Get-Command python -ErrorAction Stop).Source }
Set-Location -LiteralPath $PSScriptRoot
Write-Host 'B.AI workbench: http://127.0.0.1:8771/#/w/demo/bai'
& $taskPython (Join-Path $PSScriptRoot 'tools/bai_service.py')
