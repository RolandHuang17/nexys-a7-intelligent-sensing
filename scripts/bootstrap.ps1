param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskVenv = Join-Path $taskRoot '.venv'
$taskPython = Join-Path $taskVenv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & $Python -m venv $taskVenv
    if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败' }
}
& $taskPython -m pip install --no-index --find-links (Join-Path $taskRoot 'upstream\wheels') -r (Join-Path $taskRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw '离线依赖安装失败' }
Write-Output '离线Python环境已准备好；硬件构建还需已安装的Vivado 2026.1，报告需TeX Live 2026。'
