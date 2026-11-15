[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$pkg = 'C:\Users\roland\.platformio\packages\tool-openocd-riscv-chipsalliance'
Get-ChildItem -LiteralPath $pkg -Force | Select-Object Name,Mode | Format-Table
Get-ChildItem -LiteralPath $pkg -Filter openocd.exe -Recurse | Select-Object FullName | Format-List
Get-ChildItem -LiteralPath $pkg -Filter xilinx-xc7.cfg -Recurse | ForEach-Object { Write-Output $_.FullName; Get-Content -LiteralPath $_.FullName }
Get-Content -LiteralPath (Join-Path $pkg 'package.json') -ErrorAction SilentlyContinue
rg --files 'D:\projects\qianrushi' 'D:\projects\shiyan_qianrushi' 'D:\projects\wuxiaopingzuoye1' -g '*openocd*.cfg' -g '!**/.git/**' -g '!**/.venv/**' -g '!**/node_modules/**'
