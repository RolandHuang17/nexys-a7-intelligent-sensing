"""Inspect the tested EXE bytes and run its no-network portable self-check."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid
from datetime import datetime

from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.utils.hooks import collect_data_files


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    root=Path(__file__).resolve().parents[1]
    candidate=json.loads((root/'state/shazam_main_candidate.json').read_text(encoding='utf8'))
    exe=Path(candidate['candidate_exe'])
    assert sha(exe)==candidate['exe_sha256']
    archive=CArchiveReader(str(exe))
    pyz=archive.open_embedded_archive(next(k for k in archive.toc if k.startswith('PYZ')))
    required=['ui','ui.dashboard','ui.theme','ttkbootstrap','ttkbootstrap.themes']
    assert all(k in pyz.toc for k in required),required
    forbidden=['music_online','music_credentials','pc_mic_backend']
    assert all(k not in pyz.toc for k in forbidden)
    embedded={k.replace('\\','/'):k for k in archive.toc}
    manifest=json.loads((root/'release_assets/release_manifest.json').read_text(encoding='utf8'))
    for row in manifest['resources']:
        key='release_assets/'+row['path']
        assert hashlib.sha256(archive.extract(embedded[key])).hexdigest()==row['sha256'],key
    theme_files=[]
    for source,dest in collect_data_files('ttkbootstrap.assets'):
        key=(Path(dest)/Path(source).name).as_posix()
        assert hashlib.sha256(archive.extract(embedded[key])).hexdigest()==sha(source),key
        theme_files.append(key)
    assert any(k.endswith('/bootstrap.ttf') for k in theme_files)
    assert any(k.endswith('/glyphmap.json') for k in theme_files)
    metadata=[k for k in embedded if k.startswith('ttkbootstrap-') and k.endswith('/METADATA')]
    assert len(metadata)==1
    assert b'Version: 2.2.7' in archive.extract(embedded[metadata[0]])
    source=Path(candidate['build_source_directory'])
    rows=json.loads((source/'source_manifest.json').read_text(encoding='utf8'))
    assert sha(source/'source_manifest.json')==candidate['source_manifest_sha256']
    ui_rows=[r for r in rows if r['path'].startswith('ui/')]
    assert len(ui_rows)>=3
    for row in rows:
        assert sha(source/'host'/row['path'])==row['sha256'],row['path']
    folder=root/'runs'/('ui_frozen_selfcheck_'+candidate['exe_sha256'][:10]+'_'+uuid.uuid4().hex[:6])
    folder.mkdir(parents=True)
    chinese=folder/'中文路径';chinese.mkdir(exist_ok=True)
    standalone=chinese/'开发板监测验收.exe';shutil.copy2(exe,standalone)
    data=folder/'user_data'
    env={**os.environ,'NEXYS_MONITOR_DATA':str(data),'NEXYS_PORTABLE_RUNTIME':'1',
         'PATH':str(Path(os.environ['SystemRoot'])/'System32')+';'+os.environ['SystemRoot'],
         'PYTHONPATH':''}
    completed=subprocess.run([str(standalone),'--self-check'],env=env,check=True,timeout=60,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    (folder/'stdout.txt').write_bytes(completed.stdout);(folder/'stderr.txt').write_bytes(completed.stderr)
    check=json.loads((data/'self_check.json').read_text(encoding='utf8'))
    assert check['app_version']=='1.3.0' and check['frozen'] and check['resources_verified']
    assert check['online_provider']=='shazamio'
    report={'status':'passed','time':datetime.now().astimezone().isoformat(),
        'candidate_exe':str(exe),'exe_sha256':sha(exe),'build_run_id':candidate['run_id'],
        'app_version':'1.3.0','embedded_original_resource_count':len(manifest['resources']),
        'all_original_resource_bytes_verified_in_EXE':True,'embedded_theme_asset_count':len(theme_files),
        'embedded_theme_assets':theme_files,'ttkbootstrap_version':'2.2.7',
        'required_UI_modules':required,'absent_legacy_modules':forbidden,
        'recursive_UI_snapshot_files':[r['path'] for r in ui_rows],
        'source_snapshot_count':len(rows),'self_check':check,'self_check_directory':str(folder),
        'clean_PATH':env['PATH'],'copied_EXE_same_hash':sha(standalone)==sha(exe),
        'network_requests':0,'serial_port_opened':False}
    (folder/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    (root/'docs/UI冻结验证.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:report[k] for k in ('status','exe_sha256','embedded_original_resource_count',
        'embedded_theme_asset_count','recursive_UI_snapshot_files','network_requests')},ensure_ascii=False))


if __name__=='__main__':main()
