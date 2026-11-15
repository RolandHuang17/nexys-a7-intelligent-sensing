[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$ErrorActionPreference = 'Continue'
Get-Content -LiteralPath 'C:\Windows\INF\oem65.inf'
Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match 'VID_0403.*PID_6010' } |
 ForEach-Object {
  Write-Output $_.InstanceId
  Get-PnpDeviceProperty -InstanceId $_.InstanceId |
   Where-Object { $_.KeyName -match 'DriverInfPath|DriverProvider|DriverVersion|DriverDate|Service|HardwareIds' } |
   Select-Object KeyName,Data | Format-List
 }
Get-ChildItem -LiteralPath 'C:\Windows\System32\DriverStore\FileRepository' -Directory -Filter 'ftdi*' |
 Select-Object FullName | Format-List
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
Write-Output ('ADMINISTRATOR=' + $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))
