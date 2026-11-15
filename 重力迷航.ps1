param([switch]$Keyboard)
$ErrorActionPreference = 'Stop'
$gamePython = Join-Path $PSScriptRoot '.ui_venv\Scripts\pythonw.exe'
$gameEntry = Join-Path $PSScriptRoot 'host\tilt_game_main.py'
$gameArguments = @('"' + $gameEntry + '"')
if ($Keyboard) { $gameArguments += '--keyboard' }
Start-Process -FilePath $gamePython -ArgumentList $gameArguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
