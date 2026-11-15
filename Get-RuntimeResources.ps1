param([string]$Archive)
$ErrorActionPreference = 'Stop'
if (-not $Archive) {
    $taskDownloadDir = Join-Path $PSScriptRoot 'downloads'
    New-Item -ItemType Directory -Path $taskDownloadDir -Force | Out-Null
    $Archive = Join-Path $taskDownloadDir 'NexysMonitor-v1.6.0-runtime-resources.zip'
    Invoke-WebRequest -Uri 'https://github.com/RolandHuang17/nexys-a7-intelligent-sensing/releases/download/v1.6.0/NexysMonitor-v1.6.0-runtime-resources.zip' -OutFile $Archive
}
$taskExpectedHash = '73b2e4208be825c14427cff7d233b9675a173e1cc7263916dc2cc62bf34f4049'
$taskActualHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($taskActualHash -ne $taskExpectedHash) { throw 'Runtime archive SHA-256 mismatch' }
Expand-Archive -LiteralPath $Archive -DestinationPath $PSScriptRoot -Force
Write-Host 'Verified runtime resources restored to release_assets/'
