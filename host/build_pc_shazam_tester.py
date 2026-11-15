"""Build a separate ShazamIO-only PC tool and record frozen dependencies."""
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys

from pc_shazam_backend import VERSION, versions
from songrec_probe import digest, now, write_json


def main():
    root=Path(__file__).resolve().parent.parent
    output=root/'deliver/电脑麦克风Shazam测试'
    output.mkdir(parents=True,exist_ok=True)
    baseline=json.loads((root/'state/songrec_deployment_baseline.json').read_text(encoding='utf8'))
    assert all(digest(root/p)==h for p,h in baseline.items())
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed',
             '--name','电脑麦克风Shazam测试','--paths',str(root/'host'),'--distpath',str(output),
             '--workpath',str(root/'.portable_build/pc_shazam'),'--specpath',str(root/'scripts'),
             '--collect-submodules','shazamio','--hidden-import','shazamio_core',
             '--exclude-module','matplotlib','--exclude-module','scipy','--exclude-module','pandas',
             '--exclude-module','pytest','--exclude-module','IPython','--exclude-module','serial',
             '--exclude-module','music_board','--exclude-module','music_online','--exclude-module','music_credentials',
             '--exclude-module','monitor_gui','--exclude-module','pc_mic_backend']
    for package in ('shazamio','shazamio-core','aiohttp','aiohttp-retry','numpy'):
        command += ['--copy-metadata',package]
    command.append(str(root/'host/pc_shazam_tester.py'))
    subprocess.run(command,check=True,cwd=root)
    source=output/'源码'
    source.mkdir(exist_ok=True)
    modules=('pc_shazam_tester.py','pc_shazam_backend.py','pc_mic_capture.py','songrec_probe.py',
             'test_pc_shazam.py','build_pc_shazam_tester.py')
    for name in modules:
        shutil.copy2(root/'host'/name,source/name)
    shutil.copy2(root/'requirements-pc-shazam.txt',source/'requirements-pc-shazam.txt')
    locked=subprocess.check_output([sys.executable,'-m','pip','freeze','--all'],text=True,encoding='utf8')
    (source/'requirements-locked.txt').write_text(locked,encoding='utf8')
    packages=[]
    for distribution in importlib.metadata.distributions():
        name=distribution.metadata['Name']
        packages.append({'name':name,'version':distribution.version})
        for f in distribution.files or []:
            if not any(word in f.name.casefold() for word in ('license','copying','notice')):
                continue
            if '.dist-info' not in str(f) or not distribution.locate_file(f).is_file():
                continue
            relative=Path(str(f).split('.dist-info',1)[1].lstrip('/\\'))
            target=output/'第三方许可'/name/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(distribution.locate_file(f),target)
    manifest={'version':VERSION,'built_at':now(),'library_versions':versions(),
              'exe_sha256':digest(output/'电脑麦克风Shazam测试.exe'),'packages':packages,
              'sources':[{'path':'host/'+name,'sha256':digest(root/'host'/name)} for name in modules],
              'data_directory':'%LOCALAPPDATA%/ShazamMicTest','API_key_bundled':False,
              'AudioTag_integration':False,'board_modules_or_firmware_bundled':False,'SongRec_native_binaries_bundled':False,
              'network_policy':'minimum 30s between requests; after 429 wait at least 60s and honor longer Retry-After; one HTTP attempt, 25s async timeout, 30s owned worker deadline; no automatic retry',
              'default_capture':'20 seconds, 16000Hz mono PCM16','recognition_clip':'unmodified center 12 seconds',
              'upstream':'https://github.com/shazamio/ShazamIO','upstream_version':'https://pypi.org/project/shazamio/0.9.0/',
              'protected_files_unchanged':all(digest(root/p)==h for p,h in baseline.items())}
    assert manifest['protected_files_unchanged']
    write_json(output/'软件版本.json',manifest)
    files={str(p.relative_to(output)).replace('\\','/'):digest(p) for p in output.rglob('*') if p.is_file() and p.name!='SHA256.json'}
    write_json(output/'SHA256.json',files)
    print(json.dumps({'output':str(output),'exe_sha256':manifest['exe_sha256'],'files':len(files)},ensure_ascii=False))


if __name__=='__main__':
    main()
