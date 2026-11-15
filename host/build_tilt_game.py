"""Build an independent candidate; never calls main-app promotion scripts."""
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys

from tilt_game import VERSION

ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    stamp=datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%dT%H%M%S')
    run=ROOT/'runs'/(stamp+'_build_tilt_game')
    run.mkdir(parents=True)
    stage=ROOT/'.portable_build/tilt_game_assets/release_assets'
    stage.mkdir(parents=True,exist_ok=True)
    source=ROOT/'release_assets'
    manifest=json.loads((source/'release_manifest.json').read_text(encoding='utf8'))
    from tilt_game.render import icon_image
    icon=stage/'game_icon.ico'
    icon_image(256).save(icon,sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
    wanted=[r for r in manifest['resources'] if r['path'].startswith(('firmware/','tools/xc3sprog/','tools/openocd/'))]
    for row in wanted:
        path=source/row['path']
        assert path.is_file() and digest(path)==row['sha256'],row['path']
        target=stage/row['path']
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target)
    licenses=stage/'licenses'
    licenses.mkdir(exist_ok=True)
    (licenses/'NOTICE.txt').write_text('Gravity Voyager uses Python/Tk, Pillow, NumPy, pyserial, PyInstaller, xc3sprog (GPL), OpenOCD (GPL), libFTDI and libusb. All artwork and sound effects in this game are generated locally by the supplied source code. Firmware and programming tools are copied with SHA-256 verification from the existing Nexys A7 project. No account, credential, online recognition, or commercial music is bundled.\n',encoding='utf8')
    for name in ('numpy','pillow','pyserial','pyinstaller'):
        dist=importlib.metadata.distribution(name)
        for entry in dist.files or []:
            if any(s in entry.name.lower() for s in ('license','copying','notice')):
                path=dist.locate_file(entry)
                if path.is_file():
                    target=licenses/name/entry.name
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(path,target)
    for name in ('xc3sprog_GPL.txt','FTDI_original_license_and_header.txt'):
        path=source/'licenses'/name
        if path.exists():
            shutil.copy2(path,licenses/name)
    rows=[{'path':p.relative_to(stage).as_posix(),'sha256':digest(p),'bytes':p.stat().st_size}
          for p in sorted(stage.rglob('*')) if p.is_file() and p.name!='release_manifest.json']
    value={'app_version':VERSION,'game':'Gravity Voyager','built':datetime.now(timezone(timedelta(hours=8))).isoformat(),
           'run_id':run.name,'firmware':manifest['firmware'],'resources':rows,'independent_of_main_exe':True}
    (stage/'release_manifest.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    snapshot=run/'source'
    paths=[*sorted((ROOT/'host').glob('*tilt_game*.py')),*sorted((ROOT/'host/tilt_game').glob('*.py'))]
    source_rows=[]
    for path in paths:
        target=snapshot/path.relative_to(ROOT)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target)
        source_rows.append({'path':path.relative_to(ROOT).as_posix(),'sha256':digest(target)})
    (run/'source_manifest.json').write_text(json.dumps(source_rows,ensure_ascii=False,indent=2),encoding='utf8')
    output=ROOT/'deliver/独立小游戏'
    output.mkdir(parents=True,exist_ok=True)
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed','--name','重力迷航',
             '--paths',str(ROOT/'host'),'--add-data',str(stage)+';release_assets',
             '--distpath',str(output),'--workpath',str(ROOT/'.portable_build/tilt_game'),
             '--specpath',str(ROOT/'scripts'),'--hidden-import','PIL.ImageTk']
    command+=['--icon',str(icon)]
    for name in ('matplotlib','scipy','shazamio','shazamio_core','pytest','IPython','pymupdf',
                 'PyQt5','PyQt6','PySide2','PySide6','music_worker','music_online','music_credentials'):
        command+=['--exclude-module',name]
    command.append(str(ROOT/'host/tilt_game_main.py'))
    (run/'command.json').write_text(json.dumps(command,ensure_ascii=False,indent=2),encoding='utf8')
    with (run/'build.log').open('wb') as log:
        result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    assert result.returncode==0,'Build failed: '+str(run/'build.log')
    exe=output/'重力迷航.exe'
    record={'game_version':VERSION,'build_run':run.name,'exe_file':exe.name,'exe_sha256':digest(exe),
            'exe_bytes':exe.stat().st_size,'firmware':manifest['firmware'],
            'resource_manifest_sha256':digest(stage/'release_manifest.json'),
            'source_manifest_sha256':digest(run/'source_manifest.json'),
            'main_program_modified':False,'physical_acceptance':'pending','integration':'awaiting_user_playtest_approval'}
    for path in (output/'版本与校验.json',run/'result.json'):
        path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(record,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
