"""Package the themed main app while copying sealed offline assets verbatim."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from app_paths import APP_VERSION
from songrec_probe import digest,now,write_json


def promote(record):
    root=Path(__file__).resolve().parent.parent
    output=root/'deliver/软件';output.mkdir(exist_ok=True)
    current=output/'开发板实时监测.exe'
    if current.exists():
        old=json.loads((output/'软件版本.json').read_text(encoding='utf8'))
        backup=output/'历史版本'/(old['app_version']+'_'+digest(current)[:8])
        backup.mkdir(parents=True,exist_ok=True)
        for name in ('开发板实时监测.exe','软件版本.json','使用说明.md'):
            if (output/name).exists() and not (backup/name).exists():shutil.copy2(output/name,backup/name)
        record['previous_version_directory']=str(backup)
    assert digest(Path(record['candidate_exe']))==record['exe_sha256']
    shutil.copy2(record['candidate_exe'],current)
    write_json(output/'软件版本.json',record)
    write_json(root/'state/portable_build.json',record)
    return record


def build(candidate_only=False,firmware_build=None):
    root=Path(__file__).resolve().parent.parent
    ui_version=importlib.metadata.version('ttkbootstrap')
    assert ui_version=='2.2.7','Use the pinned ttkbootstrap 2.2.7 build environment'
    assets=root/'release_assets'
    original=json.loads((assets/'release_manifest.json').read_text(encoding='utf8'))
    for row in original['resources']:
        assert digest(assets/row['path'])==row['sha256'],row['path']
    stamp=now().replace(':','').replace('-','').replace('+0800','')+'_'+uuid.uuid4().hex[:6]
    run=root/'runs'/('build_shazam_main_'+stamp);run.mkdir(parents=True)
    stage=root/'.portable_build/shazam_main_assets/release_assets'
    shutil.copytree(assets,stage,dirs_exist_ok=True)
    firmware=dict(original['firmware'])
    if APP_VERSION.startswith(('1.4.','1.5.')) and firmware_build is None:
        passed_build=json.loads((root/'state/build/status.json').read_text(encoding='utf8'))
        assert passed_build['status']=='passed','A passed 100MHz FPGA build is required'
        firmware_build=root/'runs'/passed_build['run_id']
    if firmware_build is not None:
        build_root=Path(firmware_build).resolve()
        assert build_root.is_relative_to(root/'runs'),'FPGA build must be an audited run'
        passed_build=json.loads((build_root/'status.json').read_text(encoding='utf8'))
        inputs=json.loads((build_root/'build_inputs.json').read_text(encoding='utf8'))
        assert passed_build['status']=='passed' and inputs['parameters']['MUSIC_MAX_SAMPLES']==160000
        for row in inputs['files']:assert digest(root/row['path'])==row['sha256'],'RTL changed after build: '+row['path']
        bit=build_root/'implementation/recorder_top.bit'
        assert digest(bit)==passed_build['bitstream_sha256']
        shutil.copy2(bit,stage/'firmware/recorder_top.bit')
        firmware.update(build_run_id=build_root.name,build_id=inputs['build_id'],
            bitstream_sha256=digest(bit),config_sha256=passed_build['config_sha256'])
    notice=stage/'licenses/shazam_runtime';notice.mkdir(parents=True,exist_ok=True)
    packages=[]
    for dist in importlib.metadata.distributions():
        packages.append({'name':dist.metadata['Name'],'version':dist.version})
        for f in dist.files or []:
            if '.dist-info' not in str(f) or not any(s in f.name.lower() for s in ('license','copying','notice')):continue
            source=dist.locate_file(f)
            if source.is_file():
                target=notice/dist.metadata['Name']/Path(f).name
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    (notice/'ONLINE_PROVIDER.txt').write_text('Online recognition uses ShazamIO 0.9.0 / shazamio-core 2.0.0, an unofficial Shazam client. No API keys or paid account are used. Offline assets remain unchanged. Board-panel firmware is replaced only from an audited timing-passed build.\n',encoding='utf8')
    resources=[{'path':p.relative_to(stage).as_posix(),'sha256':digest(p),'bytes':p.stat().st_size}
               for p in sorted(stage.rglob('*')) if p.is_file() and p.name!='release_manifest.json']
    manifest={**original,'app_version':APP_VERSION,'built':now(),'run_id':run.name,'online_provider':'shazamio','firmware':firmware,
              'resources':resources,'source_assets_manifest_sha256':digest(assets/'release_manifest.json'),
              'panel_protocol_version':1 if firmware_build is not None else original.get('panel_protocol_version')}
    write_json(stage/'release_manifest.json',manifest)
    for row in original['resources']:
        if firmware_build is not None and row['path']=='firmware/recorder_top.bit':continue
        assert digest(stage/row['path'])==row['sha256'],row['path']
    snapshot=run/'source/host';snapshot.mkdir(parents=True)
    source_files=[]
    for path in sorted((root/'host').rglob('*.py')):
        relative=path.relative_to(root/'host')
        target=snapshot/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target)
        source_files.append({'path':relative.as_posix(),'sha256':digest(target),'bytes':target.stat().st_size})
    write_json(run/'source/source_manifest.json',source_files)
    frozen=subprocess.check_output([sys.executable,'-m','pip','freeze','--all'],text=True,encoding='utf8')
    (run/'requirements-locked.txt').write_text(frozen,encoding='utf8')
    output=root/'.portable_build/shazam_main_candidate';output.mkdir(parents=True,exist_ok=True)
    args=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed','--name','开发板实时监测',
          '--paths',str(root/'host'),'--add-data',str(stage)+';release_assets','--distpath',str(output),
          '--workpath',str(root/'.portable_build/shazam_main'),'--specpath',str(root/'scripts'),
          '--hidden-import','matplotlib.backends.backend_tkagg','--paths',str(root/'upstream/music/audfprint'),
          '--hidden-import','audfprint_analyze','--hidden-import','audfprint_match','--hidden-import','hash_table',
          '--hidden-import','audio_read','--hidden-import','stft','--hidden-import','psutil','--hidden-import','scipy.io',
          '--collect-submodules','shazamio','--hidden-import','shazamio_core',
          '--collect-data','ttkbootstrap.assets','--collect-submodules','ttkbootstrap.themes']
    for name in ('shazamio','shazamio-core','aiohttp','aiohttp-retry','numpy','ttkbootstrap'):args+=['--copy-metadata',name]
    for name in ('librosa','pymupdf','PyQt5','PyQt6','PySide2','PySide6','pycaw','comtypes','pytest','IPython',
                 'music_online','music_credentials','pc_mic_backend'):
        args+=['--exclude-module',name]
    args.append(str(root/'host/portable_main.py'))
    write_json(run/'command.json',args)
    with (run/'build.log').open('wb') as log:
        result=subprocess.run(args,cwd=root,stdout=log,stderr=subprocess.STDOUT)
    assert result.returncode==0,'Build failed; see '+str(run/'build.log')
    record={'run_id':run.name,'app_version':APP_VERSION,'online_provider':'shazamio','candidate_exe':str(output/'开发板实时监测.exe'),
            'exe_sha256':digest(output/'开发板实时监测.exe'),'exe_bytes':(output/'开发板实时监测.exe').stat().st_size,
            'firmware':manifest['firmware'],'resource_manifest_sha256':digest(stage/'release_manifest.json'),
            'source_assets_manifest_sha256':digest(assets/'release_manifest.json'),'offline_resources_copied_unchanged':True,
            'panel_protocol_version':manifest.get('panel_protocol_version'),
            'firmware_changed_from_previous':firmware!=original['firmware'],
            'packages':packages,'build_source_directory':str(run/'source'),'requirements_lock':str(run/'requirements-locked.txt'),
            'no_AudioTag_client_or_credentials_bundled':True,
            'ui_toolkit':'ttkbootstrap','ui_toolkit_version':ui_version,
            'source_manifest_sha256':digest(run/'source/source_manifest.json')}
    write_json(output/'软件版本.json',record)
    write_json(root/'state/shazam_main_candidate.json',record)
    write_json(run/'result.json',record)
    if not candidate_only:promote(record)
    print(json.dumps(record,ensure_ascii=False))
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--candidate-only',action='store_true')
    parser.add_argument('--firmware-build',type=Path)
    args=parser.parse_args();build(args.candidate_only,args.firmware_build)
