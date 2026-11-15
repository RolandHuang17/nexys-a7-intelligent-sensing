"""Verify the candidate EXE's full worker pipeline with archived board WAVs."""
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid

from songrec_probe import digest,now,write_json
from music_shazam import same_song


def main():
    root=Path(__file__).resolve().parent.parent
    candidate=json.loads((root/'state/shazam_main_candidate.json').read_text(encoding='utf8'))
    exe=Path(candidate['candidate_exe']);assert digest(exe)==candidate['exe_sha256']
    folder=root/'runs'/('verify_shazam_main_'+uuid.uuid4().hex[:10]);folder.mkdir(parents=True)
    data=folder/'user_data'
    env={**os.environ,'NEXYS_MONITOR_DATA':str(data),'NEXYS_PORTABLE_RUNTIME':'1'}
    subprocess.run([str(exe),'--self-check'],env=env,check=True,timeout=45,
                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    selfcheck=json.loads((data/'self_check.json').read_text(encoding='utf8'))
    assert selfcheck['app_version']=='1.2.0' and selfcheck['frozen'] and selfcheck['online_provider']=='shazamio'
    from PyInstaller.archive.readers import CArchiveReader
    archive=CArchiveReader(str(exe))
    pyz=archive.open_embedded_archive(next(name for name in archive.toc if name.startswith('PYZ')))
    assert 'music_online' not in pyz.toc and 'music_credentials' not in pyz.toc
    baseline=json.loads((root/'state/shazam_main_baseline.json').read_text(encoding='utf8'))
    protected={p:digest(root/p)==h for p,h in baseline['files'].items() if p.startswith('host/') or p in ('release_assets/firmware/recorder_top.bit','deliver/报告.pdf')}
    assert all(protected.values())
    for relative,checksum in baseline['assets'].items():
        assert digest(root/'release_assets'/relative)==checksum
        if relative!='release_manifest.json':
            member=str(Path('release_assets')/relative)
            assert hashlib.sha256(archive.extract(member)).hexdigest()==checksum,relative
    report={'time':now(),'candidate_exe':str(exe),'exe_sha256':candidate['exe_sha256'],'app_version':'1.2.0',
            'kind':'packaged_main_worker_replay_of_real_archived_board_microphone_recordings',
            'new_live_phone_recordings':False,'self_check':selfcheck,'protected_files':protected,
            'original_asset_count':len(baseline['assets']),'all_original_asset_bytes_verified_in_EXE':True,
            'AudioTag_client_and_credentials_absent_from_EXE':True,'rows':[],'status':'running','data_root':str(data)}
    write_json(folder/'result.json',report)
    process=subprocess.Popen([str(exe),'--internal-music-worker'],env=env,stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8',
                             creationflags=subprocess.CREATE_NO_WINDOW)
    messages=queue.Queue()
    def read_stdout():
        for line in process.stdout:
            try:messages.put(json.loads(line))
            except ValueError:messages.put({'invalid_line':line[:200]})
    def read_stderr():
        with (folder/'worker.stderr.txt').open('w',encoding='utf8') as stream:
            for line in process.stderr:stream.write(line)
    threading.Thread(target=read_stdout,daemon=True).start()
    threading.Thread(target=read_stderr,daemon=True).start()
    def request(action,**values):
        identifier=uuid.uuid4().hex
        process.stdin.write(json.dumps({'id':identifier,'action':action,**values},ensure_ascii=False)+'\n');process.stdin.flush()
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            item=messages.get(timeout=max(.1,deadline-time.monotonic()))
            with (folder/'worker_messages.jsonl').open('a',encoding='utf8') as stream:
                stream.write(json.dumps(item,ensure_ascii=False)+'\n')
            if item.get('id')==identifier and item.get('action')==action:
                assert item.get('ok'),item
                return item['result']
        raise TimeoutError('main worker reply deadline')
    try:
        component=request('verify',mode='auto');assert component['ok'] and component['provider']=='shazamio'
        recordings=json.loads((root/'state/music_api_phone_round.json').read_text(encoding='utf8'))['results']
        for old in recordings:
            wav=Path(old['job']['metadata']['wav']);before=digest(wav)
            result=request('match',wav=str(wav),mode='auto',game=False,metadata={**old['job']['metadata'],'validation_replay':True})
            assert digest(wav)==before
            row={'title':old['title'],'artist':old['artist'],'original_wav':str(wav),'wav_sha256':before,
                 'result':result,'correct_online':same_song(result,old) and result.get('source')=='shazamio'}
            report['rows'].append(row);write_json(folder/'result.json',report)
            print(json.dumps({'song':old['title'],'source':result.get('source'),'correct':row['correct_online'],
                              'reason':result.get('reason')},ensure_ascii=False),flush=True)
    finally:
        process.stdin.close()
        process.wait(timeout=15)
    report.update(status='passed' if all(r['correct_online'] for r in report['rows']) and len(report['rows'])==3 else 'failed',
                  correct=sum(r['correct_online'] for r in report['rows']),total=len(report['rows']),finished_at=now(),
                  component_check=component)
    from music_store import MusicStore
    store=MusicStore(data/'music')
    history=store.history(source='shazamio')
    assert len(history)==sum(r['correct_online'] for r in report['rows'])
    report['Shazam_history_rows']=len(history)
    write_json(folder/'result.json',report);write_json(root/'state/shazam_main_verification.json',report)
    print(json.dumps({'status':report['status'],'correct':report['correct'],'total':report['total'],
                      'report':str(folder/'result.json'),'selfcheck_devices':selfcheck['devices']},ensure_ascii=False),flush=True)
    assert report['status']=='passed'


if __name__=='__main__':main()
