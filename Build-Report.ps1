$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot 'report/final')
try { & latexmk -xelatex -interaction=nonstopmode -halt-on-error -file-line-error main.tex; $taskReportExit = $LASTEXITCODE }
finally { Pop-Location }
exit $taskReportExit
