$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$candidates = @(
 'C:\Windows\System32\dmgr.dll','C:\Windows\System32\djtg.dll',
 'C:\Windows\SysWOW64\dmgr.dll','C:\Windows\SysWOW64\djtg.dll',
 'D:\LearingTools\2026.1\Vivado\bin\unwrapped\win64.o\dmgr.dll',
 'D:\LearingTools\2026.1\Vivado\lib\win64.o\dmgr.dll'
)
$candidates | ForEach-Object {
 if (Test-Path -LiteralPath $_) { Get-Item -LiteralPath $_ | Select-Object FullName,Length,@{N='Version';E={$_.VersionInfo.FileVersion}} }
} | Format-List
Get-ChildItem -LiteralPath 'D:\LearingTools\2026.1\Vivado\data\xicom\cable_drivers\nt64' -Recurse -File -ErrorAction SilentlyContinue |
 Where-Object { $_.Name -match 'adept|digilent|dmgr|djtg|install' } | Select-Object FullName,Length | Format-Table -AutoSize
Get-Content -LiteralPath 'C:\Program Files (x86)\Digilent\install.log' -Tail 50 -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath 'runs' -Filter hw_server.log -Recurse | ForEach-Object {
 Write-Output $_.FullName
 Get-Content -LiteralPath $_.FullName -Tail 100
}
Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Enum\USB\VID_0403&PID_6010&MI_00\7&6532DBB&0&0000' -ErrorAction SilentlyContinue | Format-List
