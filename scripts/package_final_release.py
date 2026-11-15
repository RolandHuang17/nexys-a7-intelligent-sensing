"""Prepare a reviewed publication tree and Release assets; never contacts GitHub.

Own runtime files are copied byte-for-byte from the accepted 1.6.0 snapshot.
Large resources stay in Release assets, outside normal Git history.
"""
import argparse
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]
STAGE=ROOT.parent/'github-release/nexys-a7-intelligent-sensing'
ASSETS=ROOT/'deliver/GitHub发布包'
REPO='https://github.com/RolandHuang17/nexys-a7-intelligent-sensing'
PREFIX='NexysMonitor-v1.6.0'
EXE=PREFIX+'-win-x64.exe'
PDF=PREFIX+'-Design-Report.pdf'


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def copytree(source,dest,extensions=None):
    for p in sorted(source.rglob('*')):
        if not p.is_file() or any(x in p.parts for x in ('.git','__pycache__','.Xil','xsim.dir')):continue
        if extensions is not None and p.suffix not in extensions:continue
        target=dest/p.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)


def zipfiles(target,files):
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for source,name in sorted(files,key=lambda r:r[1]):z.write(source,name)


def package():
    build=read(ROOT/'state/portable_build.json')
    snapshot=ROOT/'deliver/软件/体感游戏更新源码'
    assert build['app_version']=='1.6.0'
    assert sha(ROOT/'deliver/软件/开发板实时监测.exe')==build['exe_sha256']
    host_manifest=read(snapshot/'source_manifest.json')
    assert len(host_manifest)==187
    for r in host_manifest:
        assert sha(ROOT/'host'/r['path'])==r['sha256'],r['path']
    fpga_inputs=read(ROOT/'runs/20261115T210422_219255_build/build_inputs.json')
    for r in fpga_inputs['files']:
        if r['path'].startswith(('rtl/','constraints/')):
            assert sha(ROOT/r['path'])==r['sha256'],r['path']
    ASSETS.mkdir(parents=True,exist_ok=True)
    STAGE.mkdir(parents=True,exist_ok=True)
    for folder,ext in (('host',{'.py'}),('rtl',{'.sv','.svh'}),('constraints',{'.xdc'}),
                       ('tests',{'.sv'}),('scripts',{'.tcl','.py','.ps1'})):
        copytree(ROOT/folder,STAGE/folder,ext)
    copytree(ROOT/'report/final',STAGE/'report/final',{'.tex','.cls','.png','.jpg','.csv','.json','.rpt'})
    shutil.copy2(ROOT/'report/final/figures/whulogo.pdf',STAGE/'report/final/figures/whulogo.pdf')
    for p in (ROOT/'config').glob('*.json'):
        dest=STAGE/'config'/p.name;dest.parent.mkdir(exist_ok=True);shutil.copy2(p,dest)
    for p in ROOT.glob('requirements*.txt'):shutil.copy2(p,STAGE/p.name)
    shutil.copy2(snapshot/'requirements-locked.txt',STAGE/'requirements-locked.txt')
    for name in ('run.ps1','monitor.ps1','重力迷航.ps1'):shutil.copy2(ROOT/name,STAGE/name)
    copytree(ROOT/'upstream/music/audfprint',STAGE/'upstream/music/audfprint',{'.py','.md','.txt'})
    for name in ('LICENSE','README.md'):
        path=ROOT/'upstream/music/audfprint'/name
        if path.exists():
            dest=STAGE/'upstream/music/audfprint'/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
    # Exact, selected original evidence. Personal runtime databases and raw music are excluded.
    originals={
        'game-integration.json':'deliver/体感游戏集成验收/验收记录.json',
        'game-physical-eight-levels.json':'deliver/独立小游戏/验收与测试/真人实板试玩/result.json',
        'shazam-archived-recording-replay.json':'state/shazam_main_verification.json',
        'triple-abort-runtime.json':'deliver/三敲与中止/三敲中止运行验证.json',
        'triple-abort-digital.json':'deliver/三敲与中止/三敲中止数字验证.json',
        'final-host-source-manifest.json':'deliver/软件/体感游戏更新源码/source_manifest.json',
        'fpga-build-inputs.json':'runs/20261115T210422_219255_build/build_inputs.json',
        'UI-validation-summary.md':'docs/UI验收总结.md',
    }
    evidence=[]
    for name,source in originals.items():
        dest=STAGE/'evidence'/name;dest.parent.mkdir(exist_ok=True);shutil.copy2(ROOT/source,dest)
        evidence.append({'published':'evidence/'+name,'original_path':source,'sha256':sha(dest)})
    copytree(ROOT/'deliver/体感游戏集成验收/真实完整事件',STAGE/'evidence/final-complete-event')
    write(STAGE/'evidence/index.json',evidence)
    # Heavy runtime files retain the original relative release_assets directory.
    runtime=ASSETS/(PREFIX+'-runtime-resources.zip')
    sealed=read(ROOT/'release_assets/release_manifest.json')
    for r in sealed['resources']:
        assert sha(ROOT/'release_assets'/r['path'])==r['sha256'],r['path']
    zipfiles(runtime,[(p,'release_assets/'+p.relative_to(ROOT/'release_assets').as_posix())
                     for p in (ROOT/'release_assets').rglob('*') if p.is_file()])
    third=[]
    for source in ('upstream/portable/xc3sprog_source.zip','upstream/portable/openocd_source.zip',
                   'upstream/portable/provenance.json','upstream/portable/xc3sprog_build.json',
                   'upstream/portable/openocd_source_provenance.json',
                   'upstream/music/ffmpeg-7.1-source.tar.xz',
                   'upstream/music/audfprint-cb03ba99feafd41b8874307f0f4e808a6ce34362.zip'):
        assert (ROOT/source).exists(),source
        third.append((ROOT/source,source))
    for source in ('upstream/portable/source','upstream/portable/compat','release_assets/licenses'):
        third.extend((p,p.relative_to(ROOT).as_posix()) for p in (ROOT/source).rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts)
    third.append((ROOT/'host/build_download_tool.py','build-instructions/build_download_tool.py'))
    additional=ROOT/'upstream/publication_sources'
    if additional.exists():
        third.extend((p,'upstream/publication_sources/'+p.name) for p in additional.iterdir() if p.is_file())
    thirdpath=ASSETS/(PREFIX+'-third-party-source.zip');zipfiles(thirdpath,third)
    shutil.copy2(ROOT/'deliver/软件/开发板实时监测.exe',ASSETS/EXE)
    shutil.copy2(ROOT/'report/final/main.pdf',ASSETS/PDF)
    write(STAGE/'.gitignore', '''.venv/
.ui_venv/
__pycache__/
*.pyc
.Xil/
build/
downloads/
release_assets/
.portable_build/
runs/
state/
music_user/
music/canonical/
*.sqlite3
*.sqlite3-wal
*.sqlite3-shm
*.key
*.pem
.env
.env.*
credentials.json
music_credentials.json
report/final/*.aux
report/final/*.log
report/final/*.toc
report/final/*.lof
report/final/*.lot
report/final/*.out
report/final/*.thm
report/final/*.xdv
report/final/*.synctex.gz
report/final/*.fdb_latexmk
report/final/*.fls
report/final/main.pdf
report/final/build-console.txt
''')
    write(STAGE/'.gitattributes','* -text\n')
    write(STAGE/'README.md',f'''# 基于 FPGA 的多模态智能感知与交互系统

**嵌入式系统课程设计 · Nexys A7-100T · 正式软件 1.6.0**

> **老师验收入口：[直接下载 Windows EXE]({REPO}/releases/download/v1.6.0/{EXE})**
>
> [设计报告 PDF]({REPO}/releases/download/v1.6.0/{PDF}) · [全部发布文件]({REPO}/releases/tag/v1.6.0) · [源码压缩包]({REPO}/releases/download/v1.6.0/{PREFIX}-source.zip)

无需安装 Python 或 Vivado。EXE 内含运行环境、配套固件和下载后端。适用 **Windows 10/11 x64**，硬件功能需要 **Nexys A7-100T**；无板时可查看界面并用键盘练习游戏。在线识曲需要网络。

![最终主程序体感游戏](report/final/figures/game.png)

## 快速验收

1. 下载 EXE，开发板接 **PROG/UART** USB 口并上电。软件按实际设备发现，不固定 COM 口。
2. 首次使用或掉电后，确认板型并点“初始化此板”；只加载 SRAM，未导出的板上临时数据会清空。
3. 实时监测页看声音、FFT、XYZ、温度、电压、开关和按键；点“抓取1.5秒”后查看波形、导出和播放。
4. 手机播放歌曲，SW15 拨上或点击进入识曲，等待就绪后连续敲桌 **三下**，相邻间隔约 0.15–1 秒。录音/传输/匹配期间可中止；结果支持历史、收藏及来源查询。
5. SW15 拨下并退出识曲，再进入“体感游戏”。按向导完成校准，轻倾移动，按住 BTNC 中键刹车。键盘练习使用方向键和空格。

首次缺少 USB 驱动时使用软件“驱动准备”引导。已有正常驱动无需重装。原数据保存在 `%LOCALAPPDATA%/NexysMonitor/`。初始化掉电丢失，下次重新加载；不写 Flash。

## 已实现能力

- FPGA 多源采集：2 MHz PDM / 16 kHz PCM、ADXL362 SPI、ADT7420 I²C、XADC、GPIO；统一 100 MHz 时基。
- 声振记录：手动与三类触发策略，前 0.5 秒＋后 1 秒，双组缓存，完整校验后确认释放。
- 智能音频应用：20 秒 8 kHz 完整录音，ShazamIO 在线优先、本地 audfprint 回退，三敲启动和跨阶段中止。
- 数据管理：歌曲导入、历史/次数查询、去重收藏、本地抢歌名。
- 板载反馈：LED/RGB/数码管按真实阶段显示，SW15 进入和退出识曲。
- 体感交互：八关重力迷航、握持/方向校准、中键刹车、失焦暂停、进度保存；与主程序共用唯一 UART 服务。

AI 关联集中在多模态感知、特征表达、音频检索和反馈链路。自研工程与第三方识别能力分别说明；模型训练与端侧神经网络推理列为后续扩展。

## 源码运行（Windows / Python 3.12 x64）

```powershell
py -3.12 -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install -r requirements-locked.txt
.\\Get-RuntimeResources.ps1
.\\Start-From-Source.ps1
# 无开发板时先查看界面
.\\Start-From-Source.ps1 -NoConnect
```

资源恢复脚本下载固定 Release 文件并核对 SHA-256，展开到 `release_assets/`。也可先手动下载运行资源包，然后执行 `Get-RuntimeResources.ps1 -Archive <本地ZIP>`。源码启动使用独立的 `NexysMonitorSource` 用户目录。密封资源清单引用的依赖字节码随资源原样保留；启动脚本禁止重写字节码，以保持资源哈希。

原 `run.ps1`、维护/实验脚本保留为历史研发工具；它们可能引用未随公开包复制的完整本地 `runs/state` 归档。日常源码运行使用上述入口，正文表格输入在 `report/final/data/`，精选原验收材料在 `evidence/`。

## 构建与验证

```powershell
# 在同一固定依赖环境中重新打包；不替换正式 EXE
.\\.venv\\Scripts\\python.exe host/build_shazam_main.py --candidate-only
# 报告：需要完整 TeX Live 与中文字体
.\\Build-Report.ps1
# 不打开串口、不发送音频的数字检查
.\\.venv\\Scripts\\python.exe -m unittest discover -s host -p test_game_session.py -v
.\\.venv\\Scripts\\python.exe -m unittest discover -s host -p test_tilt_game.py -v
```

硬件重建使用 Vivado 2026.1，执行 `scripts/build.tcl`，Tcl 参数依次为工程根目录、输出目录、`160000`；目标 `xc7a100tcsg324-1`。例如在已配置 Vivado 的 PowerShell 中：

```powershell
vivado -mode batch -source scripts/build.tcl -tclargs "$PWD" "$PWD/build/fpga" 160000
```

源码、约束、依赖和构建步骤用于功能复现。不同环境重新打包不保证 EXE 字节一致；正式下载文件以发布页 SHA-256 清单为准。

## 版本与已有验证

正式 EXE SHA-256：`{build['exe_sha256']}`。

固件：`{build['firmware']['build_id']}`；100 MHz 实现 WNS +0.102 ns、WHS +0.026 ns；BRAM 119.5/135，DSP 9/240。

最终集成已有 100 项自动检查、一个 UART 线程、真实完整事件导出与配置恢复；最终 EXE 内 158 项原资源核对通过。八关为已保存的真人实板试玩；三首识曲成功为真实板载录音的在线回放，分别标注来源。完整说明见报告与 `evidence/index.json`。

本机验收不外推到另一台电脑、第二块板或尚未实测的常规 FTDI 实板路径。实时预览允许有缺口，完整数据使用校验后的事件；传感器未作外部仪表绝对标定。

## 目录与第三方组件

| 目录 | 内容 |
|---|---|
| `rtl/`, `constraints/`, `tests/` | FPGA 电路、约束与 RTL 测试 |
| `host/` | 已验收 1.6.0 的 187 个 Python 文件 |
| `scripts/` | 构建、验证和报告辅助工具 |
| `report/final/` | 最终 LaTeX/TikZ、图片与数据 |
| `evidence/` | 精选原验收记录与完整事件 |
| `publication/` | 版本、资源哈希与源码组成 |

大型运行资源与第三方工具对应源码在 Release，许可及署名见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。商业歌曲完整原曲、个人数据库与凭据不进入公开包。公开可见不自动授予自研文件新的统一开源许可证；第三方组件沿用原许可证。
''')
    write(STAGE/'Get-RuntimeResources.ps1',f'''param([string]$Archive)
$ErrorActionPreference = 'Stop'
if (-not $Archive) {{
    $taskDownloadDir = Join-Path $PSScriptRoot 'downloads'
    New-Item -ItemType Directory -Path $taskDownloadDir -Force | Out-Null
    $Archive = Join-Path $taskDownloadDir '{runtime.name}'
    Invoke-WebRequest -Uri '{REPO}/releases/download/v1.6.0/{runtime.name}' -OutFile $Archive
}}
$taskExpectedHash = '{sha(runtime)}'
$taskActualHash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($taskActualHash -ne $taskExpectedHash) {{ throw 'Runtime archive SHA-256 mismatch' }}
Expand-Archive -LiteralPath $Archive -DestinationPath $PSScriptRoot -Force
Write-Host 'Verified runtime resources restored to release_assets/'
''')
    write(STAGE/'Start-From-Source.ps1','''param([switch]$NoConnect)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Create .venv and install requirements-locked.txt first' }
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'release_assets/release_manifest.json'))) { throw 'Run Get-RuntimeResources.ps1 first' }
$env:NEXYS_PORTABLE_RUNTIME = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:NEXYS_MONITOR_DATA = Join-Path $env:LOCALAPPDATA 'NexysMonitorSource'
$taskSourceArgs = @()
if ($NoConnect) { $taskSourceArgs += '--no-connect' }
& $taskPython (Join-Path $PSScriptRoot 'host/portable_main.py') @taskSourceArgs
exit $LASTEXITCODE
''')
    write(STAGE/'Build-Report.ps1','''$ErrorActionPreference = 'Stop'
Push-Location (Join-Path $PSScriptRoot 'report/final')
try { & latexmk -xelatex -interaction=nonstopmode -halt-on-error -file-line-error main.tex; $taskReportExit = $LASTEXITCODE }
finally { Pop-Location }
exit $taskReportExit
''')
    write(STAGE/'THIRD_PARTY_NOTICES.md','''# Third-party notices and corresponding sources

The original license texts and distribution metadata are included in the runtime archive under `release_assets/licenses/`, and are also included in the third-party-source Release asset. This project does not relicense those components.

| Component | Version / pinned source | Source and terms |
|---|---|---|
| Python / Tcl-Tk | Build environment recorded in dependency/source manifests | Python PSF and Tcl/Tk terms; vendor runtime notices retained |
| NumPy / SciPy / Matplotlib / Pillow / pyserial / ttkbootstrap / PyInstaller and Python dependencies | `requirements-locked.txt` | Original distribution license metadata retained under `licenses/` |
| ShazamIO / shazamio-core | 0.9.0 / 2.0.0 | https://github.com/shazamio/ShazamIO — unofficial client; upstream MIT notices retained |
| audfprint | cb03ba99feafd41b8874307f0f4e808a6ce34362 | https://github.com/dpwe/audfprint — MIT; pinned source included |
| FFmpeg | 7.1, imageio-ffmpeg GPL build | ffmpeg-7.1-source.tar.xz in third-party-source asset; original source at https://ffmpeg.org/ |
| xc3sprog | f4bebd014da3e7e8f6b04dbe41de089b256a9a1b | GPL-2.0-or-later; pinned source archive, local source and build script included |
| OpenOCD | 0.11.0+dev-02060-g857b5cec1 | GPL-2.0-or-later; riscv-openocd pinned corresponding source archive and provenance included |
| libFTDI / libusb | 1.5 / 1.0.23, original OpenOCD distribution DLLs | LGPL component terms; versioned source archives and provenance included; upstream https://www.intra2net.com/en/developer/libftdi/ and https://libusb.info/ |
| FTDI D2XX / driver | Original vendor files, driver 2.12.36.20 | Vendor terms retained; use for FTDI devices, original header and installer notices retained |
| WHUExperiment | 000c2b12693d9b914bfaf4f1ddfe2476a679cf6e | Original report class and logo retained; https://github.com/xiaoxinganling/WHUExperiment |

Demonstration recordings by Kevin MacLeod, Scott Buckley and other credited artists retain the CC BY 4.0 attribution supplied with the original assets. See `release_assets/music_demo/署名与用途.txt` for exact track credits. The public archive does not include complete commercial song masters; limited local fingerprint entries are kept as originally shipped.

The hardware/host implementation is the student's course project; the report identifies external components and services separately from self-authored work. No endorsement or official Shazam API status is implied.
''')
    record={k:build[k] for k in ('app_version','exe_sha256','exe_bytes','firmware','online_provider','resource_manifest_sha256','source_manifest_sha256')}
    record.update(repository=REPO,tag='v1.6.0',accepted_host_files=len(host_manifest),
                  generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
                  source_assets_manifest_sha256=sha(ROOT/'release_assets/release_manifest.json'),
                  asset_files=[{'name':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in (ASSETS/EXE,ASSETS/PDF,runtime,thirdpath)])
    write(STAGE/'publication/release.json',record)
    write(STAGE/'publication/accepted-host-source.json',host_manifest)
    write(STAGE/'publication/source-boundary.md','''# Publication boundary

The 187 `host/` Python files match the accepted 1.6.0 source manifest byte-for-byte. RTL, constraints and final firmware are bound to ec0351f8. Added report/publication scripts do not alter runtime behavior. Large resources are restored separately from the fixed Release archive.

Evidence JSON files are selected original records and may contain historical absolute paths; these identify original inputs and do not need to exist when compiling the final report. Standalone report inputs are checked into `report/final/data/`. Historical maintenance tools expecting the full private workspace are retained for inspection, not advertised as the public quick-start workflow.
''')
    release_notes=f'''# 1.6.0 — 多模态智能感知与交互系统

**老师验收请下载 `{EXE}`，无需安装 Python 或 Vivado。**

适用 Windows 10/11 x64 与 Nexys A7-100T。首次连接或板卡掉电后，在软件中确认板型并初始化 SRAM；在线识曲需网络。无板可用键盘练习游戏。

- 实时声音/FFT/XYZ/温度/电压/GPIO，完整 1.5 秒事件与回放。
- 三敲听歌识曲、跨阶段中止、Shazam 在线优先及本地指纹回退、历史与收藏。
- 板载 LED/RGB/数码管状态反馈，SW15 识曲模式。
- 主程序八关体感游戏、握持校准、中键刹车、模式互斥和状态恢复。

| 文件 | 用途 |
|---|---|
| `{EXE}` | 直接运行的正式软件 |
| `{PDF}` | 最终设计报告，封面含下载入口 |
| `{PREFIX}-source.zip` | 与仓库一致的源代码及报告源码 |
| `{PREFIX}-runtime-resources.zip` | 源码运行/重打包所需资源 |
| `{PREFIX}-third-party-source.zip` | 第三方工具固定源码、构建材料和许可证 |
| `SHA256SUMS.txt` | 下载校验 |

EXE SHA-256：`{build['exe_sha256']}`。固件：`{build['firmware']['build_id']}`。软件使用已验收原件，未因报告重写重新打包。

验证与复现口径见报告和 README：三首识曲结果为真实板载录音回放，八关为保留的真人实板验收；最终集成使用一个 UART 服务，并核对 158 项原资源。
'''
    write(ASSETS/'RELEASE_NOTES.md',release_notes)
    # Review actual publication contents, not the giant development workspace.
    forbidden_names={'credentials.json','music_credentials.json','music_account_attestation.json','.env'}
    secret=re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
    violations=[]
    files=[]
    for p in sorted(STAGE.rglob('*')):
        if not p.is_file() or '.git' in p.parts:continue
        rel=p.relative_to(STAGE).as_posix()
        if p.relative_to(STAGE).parts[0] in ('release_assets','runs','state','downloads','build','.venv','.ui_venv','.portable_build') or '__pycache__' in p.parts:continue
        if rel=='publication/source-files.json':continue
        if rel.startswith('report/final/') and (p.suffix in ('.aux','.log','.toc','.lof','.lot','.out','.thm','.xdv','.fls','.fdb_latexmk') or p.name in ('main.pdf','main.synctex.gz','build-console.txt')):continue
        if p.name in forbidden_names or p.suffix in ('.sqlite3','.key','.pem','.exe','.dll'):
            violations.append(rel)
        if p.stat().st_size>=100*1024**2:violations.append('oversized:'+rel)
        if p.stat().st_size<10*1024**2 and secret.search(p.read_bytes()):violations.append('secret-pattern:'+rel)
        files.append({'path':rel,'bytes':p.stat().st_size,'sha256':sha(p)})
    assert not violations,violations
    write(STAGE/'publication/source-files.json',files)
    # Source ZIP contains reviewed source files only; excludes subsequent local build products.
    files.append({'path':'publication/source-files.json'})
    sourcezip=ASSETS/(PREFIX+'-source.zip')
    zipfiles(sourcezip,[(STAGE/r['path'],r['path']) for r in files])
    write(ASSETS/'SHA256SUMS.txt',''.join(sha(p)+'  '+p.name+'\n' for p in (ASSETS/EXE,ASSETS/PDF,sourcezip,runtime,thirdpath)))
    write(ASSETS/'publication-check.json',{'stage':str(STAGE),'source_files':len(files),'accepted_host_files':len(host_manifest),
        'publication_violations':violations,'asset_hashes':[{ 'name':p.name,'sha256':sha(p),'bytes':p.stat().st_size }
        for p in (ASSETS/EXE,ASSETS/PDF,sourcezip,runtime,thirdpath)],'created_at':record['generated_at']})
    print(json.dumps({'stage':str(STAGE),'assets':str(ASSETS),'source_files':len(files),'violations':violations},ensure_ascii=False))


if __name__=='__main__':
    package()
