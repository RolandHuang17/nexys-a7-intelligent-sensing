param([switch]$NoConnect)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Create .venv and install requirements-locked.txt first' }
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'release_assets/release_manifest.json'))) { throw 'Run Get-RuntimeResources.ps1 first' }
$env:NEXYS_PORTABLE_RUNTIME = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:NEXYS_MONITOR_DATA = Join-Path $env:LOCALAPPDATA 'NexysMonitorSource'
$taskSourceArgs = @()
if ($NoConnect) { $taskSourceArgs += '--no-connect' }
& $taskPython (Join-Path $PSScriptRoot 'host/portable_main.py') @taskSourceArgs
exit $LASTEXITCODE
