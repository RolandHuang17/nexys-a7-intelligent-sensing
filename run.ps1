param(
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet('doctor','baseline','build','selftest','collect','evaluate','report','monitor')]
    [string]$Action,
    [Parameter(ValueFromRemainingArguments=$true)] [string[]]$ExtraArgs
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { $projectPython = (Get-Command python).Source }
if($Action -eq 'monitor') { & $projectPython (Join-Path $PSScriptRoot 'host\monitor_gui.py') @ExtraArgs }
else { & $projectPython (Join-Path $PSScriptRoot 'host\harness.py') $Action @ExtraArgs }
exit $LASTEXITCODE
