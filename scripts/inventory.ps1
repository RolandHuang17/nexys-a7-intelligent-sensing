$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$devices = @(Get-PnpDevice -PresentOnly | Where-Object {
    $_.InstanceId -match 'VID_0403|VID_1443|DIGILENT|XILINX' -or
    $_.FriendlyName -match 'Digilent|Xilinx|USB Serial|USB UART|Nexys'
} | Select-Object Class,FriendlyName,InstanceId,Status)
$serial = @(Get-CimInstance Win32_SerialPort | Select-Object DeviceID,Name,PNPDeviceID)
$processes = @(Get-Process vivado,hw_server,cs_server,xsdb -ErrorAction SilentlyContinue |
    Select-Object ProcessName,Id,Path)
$runtime = @('C:\Program Files (x86)\Common Files\Digilent','C:\Program Files\Common Files\Digilent') |
    Where-Object { Test-Path -LiteralPath $_ } | ForEach-Object {
        Get-ChildItem -LiteralPath $_ -Recurse -File | Where-Object { $_.Extension -in @('.dll','.exe','.h') } |
            Select-Object FullName,Length,@{N='Version';E={$_.VersionInfo.FileVersion}}
    }
[pscustomobject]@{
    devices=$devices; serial=$serial; processes=$processes; adept_runtime=@($runtime)
    port_exclusions=(netsh interface ipv4 show excludedportrange protocol=tcp | Out-String)
    commands=@(Get-Command python,git,latexmk,xelatex,pdftoppm -ErrorAction SilentlyContinue |
        Select-Object Name,Source)
} | ConvertTo-Json -Depth 6
