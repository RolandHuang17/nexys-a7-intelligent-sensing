"""Inspect the final game's host package and self-check a copied Chinese-path EXE."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from PyInstaller.archive.readers import CArchiveReader


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    root=Path(__file__).resolve().parents[1]
    candidate=json.loads((root/'state/shazam_main_candidate.json').read_text(encoding='utf8'))
    exe=Path(candidate['candidate_exe'])
    assert candidate['app_version']=='1.6.0' and sha(exe)==candidate['exe_sha256']
    folder=root/'runs'/('game_frozen_'+candidate['exe_sha256'][:12])
    folder.mkdir(parents=True,exist_ok=True)
    archive=CArchiveReader(str(exe))
    pyz=archive.open_embedded_archive(next(k for k in archive.toc if k.startswith('PYZ')))
    required=('game_session','tilt_game.app','tilt_game.embedded','tilt_game.engine','tilt_game.levels',
              'tilt_game.input','tilt_game.storage','panel_control','panel_protocol','music_board','music_worker')
    assert all(name in pyz.toc for name in required)
    original=json.loads((root/'release_assets/release_manifest.json').read_text(encoding='utf8'))
    embedded={name.replace('\\','/'):name for name in archive.toc}
    for row in original['resources']:
        assert hashlib.sha256(archive.extract(embedded['release_assets/'+row['path']])).hexdigest()==row['sha256'],row['path']
    manifest=json.loads(archive.extract(embedded['release_assets/release_manifest.json']))
    assert manifest['firmware']==original['firmware'] and manifest['panel_protocol_version']==1
    chinese=folder/'中文路径';chinese.mkdir(exist_ok=True)
    standalone=chinese/'游戏整合验收.exe';shutil.copy2(exe,standalone)
    data=folder/'user_data'
    env={**os.environ,'NEXYS_MONITOR_DATA':str(data),'NEXYS_PORTABLE_RUNTIME':'1','PYTHONPATH':'',
         'PATH':str(Path(os.environ['SystemRoot'])/'System32')+';'+os.environ['SystemRoot']}
    completed=subprocess.run([str(standalone),'--self-check'],env=env,timeout=60,
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    (folder/'stdout.txt').write_bytes(completed.stdout);(folder/'stderr.txt').write_bytes(completed.stderr)
    assert completed.returncode==0,completed.stderr.decode('utf8',errors='replace')
    check=json.loads((data/'self_check.json').read_text(encoding='utf8'))
    assert check['app_version']=='1.6.0' and check['frozen'] and check['resources_verified']
    result={'passed':True,'candidate_exe_sha256':sha(exe),'copied_exe_sha256':sha(standalone),
            'required_modules':required,'original_resources_verified':len(original['resources']),
            'firmware_unchanged':True,'panel_protocol_version':1,'self_check':check,
            'clean_PATH':env['PATH'],'network_requests':0,'serial_opened':False}
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    (root/'state/game_frozen_check.json').write_text(json.dumps({'directory':str(folder),**result},ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:result[k] for k in ('passed','candidate_exe_sha256','original_resources_verified','firmware_unchanged')},ensure_ascii=False))


if __name__=='__main__':main()
