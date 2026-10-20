$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = (Get-Command python -ErrorAction Stop).Source }
Set-Location -LiteralPath $PSScriptRoot
& $taskPython (Join-Path $PSScriptRoot 'tools/geo_flow.py')
