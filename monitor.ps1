param([switch]$Program,[switch]$NoConnect)
$ErrorActionPreference='Stop'
$env:PYTHONUTF8='1'
$monitorPython=$null
$availablePython=@()
foreach($environmentName in @('.ui_venv','.board_shazam_venv','.venv')){
    $candidatePython=Join-Path $PSScriptRoot ($environmentName+'\Scripts\python.exe')
    if(!(Test-Path -LiteralPath $candidatePython)){continue}
    $availablePython+=,$candidatePython
    & $candidatePython -c "import importlib.metadata as m,sys; expected={'ttkbootstrap':'2.2.7','numpy':'1.26.4','matplotlib':'3.10.1','pyserial':'3.5','shazamio':'0.9.0','shazamio-core':'2.0.0'}; available={d.metadata['Name'].lower().replace('_','-'):d.version for d in m.distributions()}; sys.exit(0 if all(available.get(k)==v for k,v in expected.items()) else 1)" 2>$null
    if($LASTEXITCODE -eq 0){$monitorPython=$candidatePython;break}
}
if(!$monitorPython){
    Write-Host '未找到完整的固定版本UI运行环境。可以直接运行 deliver\软件\开发板实时监测.exe。'
    Write-Host '原1.2.0识曲环境仅缺ttkbootstrap时，可使用随附本机wheel补齐（不会自动安装或联网）：'
    $suggestedPython=if($availablePython.Count){$availablePython[0]}else{'<Python 3.12路径>'}
    Write-Host ('& "'+$suggestedPython+'" -m pip install --no-index --no-deps --find-links "'+(Join-Path $PSScriptRoot 'upstream\ui\wheels')+'" ttkbootstrap==2.2.7')
    Write-Host '完整环境复现见 docs\UI构建说明.md 和 deliver\UI重构验收\requirements-locked.txt。'
    exit 1
}
$monitorArgs=@()
if($Program){$monitorArgs+='--program'}
if($NoConnect){$monitorArgs+='--no-connect'}
& $monitorPython (Join-Path $PSScriptRoot 'host\monitor_gui.py') @monitorArgs
exit $LASTEXITCODE
