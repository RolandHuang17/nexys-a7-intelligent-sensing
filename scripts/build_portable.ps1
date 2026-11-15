param([switch]$RebuildDownloadTool,[switch]$CandidateOnly)
$ErrorActionPreference='Stop'
$portableRoot=Split-Path -Parent $PSScriptRoot
$bootstrapPython=Join-Path $portableRoot '.venv\Scripts\python.exe'
$portablePython=Join-Path $portableRoot '.package_venv\Scripts\python.exe'
$uiPython=Join-Path $portableRoot '.ui_venv\Scripts\python.exe'
if(Test-Path -LiteralPath $uiPython){$portablePython=$uiPython}
Push-Location $portableRoot
try {
    if(!(Test-Path -LiteralPath $portablePython)){
        & $bootstrapPython -m venv '.package_venv'
        if($LASTEXITCODE -ne 0){throw '隔离打包环境创建失败'}
    }
    & $portablePython -m pip install --no-index --find-links 'upstream\wheels' --find-links 'upstream\portable\wheels' --find-links 'upstream\ui\wheels' -r 'requirements-runtime.txt' -r 'requirements-portable-build.txt'
    if($LASTEXITCODE -ne 0){throw '离线打包依赖未准备好'}
    if($RebuildDownloadTool){
        & $portablePython 'host\audit.py' exec --purpose '重新构建D2XX下载工具' --timeout 360 -- $portablePython 'host\build_download_tool.py'
        if($LASTEXITCODE -ne 0){throw '下载工具构建失败'}
    }
    if($CandidateOnly){
        & $portablePython 'host\audit.py' exec --purpose '构建UI候选单文件EXE（不替换正式版）' --timeout 900 -- $portablePython 'host\build_shazam_main.py' --candidate-only
    } else {
        & $portablePython 'host\audit.py' exec --purpose '重新构建独立EXE' --timeout 900 -- $portablePython 'host\build_portable.py'
    }
    if($LASTEXITCODE -ne 0){throw 'EXE构建失败'}
} finally {Pop-Location}
