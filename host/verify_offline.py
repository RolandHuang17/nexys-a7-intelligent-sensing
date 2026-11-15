from audit import ROOT,Run,sha256,write_json
import sys

run=Run('offline_dependencies');run.snapshot('在独立空环境中仅使用归档wheel验证离线依赖')
environment=ROOT/'.offline_verify';python=environment/'Scripts/python.exe'
if not python.exists():
    rc,text=run.command([sys.executable,'-m','venv',environment],'创建独立干净虚拟环境',timeout=120)
    if rc:raise RuntimeError('venv failed')
rc,text=run.command([python,'-m','pip','install','--no-index','--find-links',ROOT/'upstream/wheels','-r',ROOT/'requirements.txt'],
                    '禁止索引访问，从本地固定wheel安装全部核心依赖',timeout=180)
if rc:raise RuntimeError('offline pip failed')
rc,text=run.command([python,'-c',"import numpy,matplotlib,serial,PIL,pymupdf,tkinter; print(numpy.__version__,matplotlib.__version__,serial.__version__,PIL.__version__,pymupdf.__version__);print('OFFLINE_IMPORT_PASS')"],
                    '独立环境导入数值、绘图、串口、PDF和中文引导依赖')
if rc:raise RuntimeError('offline import failed')
write_json(run.path/'wheels.json',[{'file':p.name,'sha256':sha256(p)} for p in (ROOT/'upstream/wheels').glob('*.whl')])
run.manifest();print('RUN_ID='+run.run_id)
