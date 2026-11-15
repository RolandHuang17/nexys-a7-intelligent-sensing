"""Inspect 1.5.0 frozen bytes; allow only the new firmware among sealed assets.

Runs a no-network, no-UART-open --self-check in a fresh Chinese-path profile.
Never programs a board or promotes the candidate.
"""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from PyInstaller.archive.readers import CArchiveReader
from PyInstaller.utils.hooks import collect_data_files


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    root=Path(__file__).resolve().parents[1]
    candidate=json.loads((root/'state/shazam_main_candidate.json').read_text(encoding='utf8'))
    assert candidate['app_version']=='1.5.0','Wait for the 1.5.0 candidate build'
    exe=Path(candidate['candidate_exe']);assert sha(exe)==candidate['exe_sha256']
    archive=CArchiveReader(str(exe));members={k.replace('\\','/'):k for k in archive.toc}
    pyz=archive.open_embedded_archive(next(k for k in archive.toc if k.startswith('PYZ')))
    required=['music_worker','music_board','music_gui','music_protocol','panel_protocol','panel_control','ui','ui.dashboard','ui.theme','ttkbootstrap']
    assert all(name in pyz.toc for name in required),required
    forbidden=['music_online','music_credentials','pc_mic_backend']
    assert all(name not in pyz.toc for name in forbidden)
    original=json.loads((root/'release_assets/release_manifest.json').read_text(encoding='utf8'))
    firmware_path='firmware/recorder_top.bit';unchanged=[]
    embedded_firmware=None
    for row in original['resources']:
        actual=hashlib.sha256(archive.extract(members['release_assets/'+row['path']])).hexdigest()
        if row['path']==firmware_path:
            assert actual==candidate['firmware']['bitstream_sha256']
            assert actual!=row['sha256'],'Panel release must contain the new board firmware'
            embedded_firmware=actual
        else:
            assert actual==row['sha256'],row['path'];unchanged.append(row['path'])
    assert embedded_firmware
    embedded_manifest=json.loads(archive.extract(members['release_assets/release_manifest.json']).decode('utf8'))
    assert embedded_manifest['app_version']=='1.5.0'
    assert embedded_manifest['firmware']==candidate['firmware']
    # Validate every resource listed by the new embedded manifest too, including
    # licenses added during packaging, rather than trusting its assertion alone.
    for row in embedded_manifest['resources']:
        assert hashlib.sha256(archive.extract(members['release_assets/'+row['path']])).hexdigest()==row['sha256'],row['path']
    theme_files=[]
    for source,dest in collect_data_files('ttkbootstrap.assets'):
        name=(Path(dest)/Path(source).name).as_posix()
        assert hashlib.sha256(archive.extract(members[name])).hexdigest()==sha(source),name
        theme_files.append(name)
    assert any(name.endswith('/bootstrap.ttf') for name in theme_files)
    assert any(name.endswith('/glyphmap.json') for name in theme_files)
    toolkit_metadata=next(name for name in members if name.startswith('ttkbootstrap-') and name.endswith('/METADATA'))
    assert b'Version: 2.2.7' in archive.extract(members[toolkit_metadata])
    source=Path(candidate['build_source_directory']);manifest=source/'source_manifest.json'
    assert sha(manifest)==candidate['source_manifest_sha256']
    source_rows=json.loads(manifest.read_text(encoding='utf8'))
    names={row['path'] for row in source_rows}
    assert {'panel_protocol.py','panel_control.py','test_panel_host.py'}.issubset(names)
    assert any(name.startswith('ui/') for name in names)
    for row in source_rows:assert sha(source/'host'/row['path'])==row['sha256'],row['path']
    folder=root/'runs'/('panel_frozen_selfcheck_'+candidate['exe_sha256'][:10]+'_'+uuid.uuid4().hex[:6])
    chinese=folder/'中文路径';chinese.mkdir(parents=True)
    standalone=chinese/'板载面板监测验收.exe';shutil.copy2(exe,standalone)
    profile=folder/'user_data'
    environment={**os.environ,'NEXYS_MONITOR_DATA':str(profile),'NEXYS_PORTABLE_RUNTIME':'1',
        'PATH':str(Path(os.environ['SystemRoot'])/'System32')+';'+os.environ['SystemRoot'],'PYTHONPATH':''}
    process=subprocess.run([str(standalone),'--self-check'],env=environment,check=True,timeout=60,
        stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    (folder/'stdout.txt').write_bytes(process.stdout);(folder/'stderr.txt').write_bytes(process.stderr)
    check=json.loads((profile/'self_check.json').read_text(encoding='utf8'))
    assert check['app_version']=='1.5.0' and check['frozen'] and check['resources_verified']
    assert check['firmware']['bitstream_sha256']==embedded_firmware and check['online_provider']=='shazamio'
    result={'status':'passed','time':datetime.now().astimezone().isoformat(),'app_version':'1.5.0',
        'candidate_exe':str(exe),'exe_sha256':sha(exe),'build_run_id':candidate['run_id'],
        'all_original_nonfirmware_asset_bytes_unchanged':True,'unchanged_original_asset_count':len(unchanged),
        'allowed_original_asset_changes':[firmware_path],'embedded_new_firmware_sha256':embedded_firmware,
        'new_embedded_manifest_resource_count':len(embedded_manifest['resources']),
        'all_embedded_manifest_resource_hashes_verified':True,
        'theme_asset_count':len(theme_files),'theme_assets':theme_files,'ttkbootstrap_version':'2.2.7',
        'required_PYZ_modules':required,'absent_legacy_modules':forbidden,
        'source_snapshot_files':len(source_rows),'new_panel_source_snapshot':sorted(n for n in names if 'panel' in n),
        'requirements_lock':candidate['requirements_lock'],'requirements_lock_sha256':sha(candidate['requirements_lock']),
        'self_check':check,'self_check_directory':str(folder),'clean_PATH':environment['PATH'],
        'copied_EXE_same_hash':sha(standalone)==sha(exe),'network_requests':0,'serial_port_opened':False,
        'firmware_programmed':False,'historical_UI_1_3_report_overwritten':False}
    text=json.dumps(result,ensure_ascii=False,indent=2)
    (folder/'result.json').write_text(text,encoding='utf8')
    (root/'docs/三敲中止冻结验证.json').write_text(text,encoding='utf8')
    print(json.dumps({k:result[k] for k in ('status','exe_sha256','unchanged_original_asset_count',
        'theme_asset_count','embedded_new_firmware_sha256','network_requests')},ensure_ascii=False))


if __name__=='__main__':main()
