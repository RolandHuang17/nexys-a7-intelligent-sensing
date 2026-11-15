param([Parameter(Mandatory=$true)][string]$CollectionRunId)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
$taskLog = Join-Path $taskRoot 'runs\experiment_flow_stdout.log'
$taskError = Join-Path $taskRoot 'runs\experiment_flow_stderr.log'
$taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('host/after_collect.py',$CollectionRunId) -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput $taskLog -RedirectStandardError $taskError -PassThru
Write-Output $taskProcess.Id
