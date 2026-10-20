$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = (Get-Command python -ErrorAction Stop).Source }
$taskRuntime = Join-Path $taskRoot 'runtime'
New-Item -ItemType Directory -Path $taskRuntime -Force | Out-Null
foreach ($taskService in @(@{port=8770;file='native_service.py';name='service'},@{port=8771;file='bai_service.py';name='bai-service'},@{port=8772;file='geo_flow.py';name='research-service'})) {
    $taskSocket = New-Object System.Net.Sockets.TcpClient
    try { $taskSocket.Connect('127.0.0.1',$taskService.port); $taskRunning = $true } catch { $taskRunning = $false } finally { $taskSocket.Dispose() }
    if (-not $taskRunning) {
        $taskScript = Join-Path $taskRoot ('tools/' + $taskService.file)
        $taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('"' + $taskScript + '"') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskRuntime ($taskService.name + '.stdout.log')) -RedirectStandardError (Join-Path $taskRuntime ($taskService.name + '.stderr.log')) -PassThru
        $taskProcess.Id | Set-Content -LiteralPath (Join-Path $taskRuntime ($taskService.name + '.pid'))
    }
}
Write-Host 'Signal GEO: http://127.0.0.1:8772/#/w/demo/research'
Write-Host 'Existing key sessions are preserved. After a computer restart, reconnect your API keys in the model settings pages.'
Start-Process 'http://127.0.0.1:8772/#/w/demo/research'
