"""Run the EXE's actual piped worker with Python/Vivado absent from PATH."""
import json,os,queue,shutil,subprocess,threading,uuid
from pathlib import Path
from audit import ROOT,Run,write_json,sha256

if __name__=='__main__':
    r=Run('music_packaged_worker_test');folder=r.path/'isolated_only_exe';folder.mkdir()
    source=ROOT/'deliver/软件/开发板实时监测.exe';exe=folder/source.name;shutil.copy2(source,exe)
    env={**os.environ,'PATH':str(Path(os.environ['SystemRoot'])/'System32'),'PYTHONPATH':'','NEXYS_MONITOR_DATA':str(r.path/'userdata')}
    p=subprocess.Popen([str(exe),'--internal-music-worker'],cwd=folder,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8',creationflags=subprocess.CREATE_NO_WINDOW)
    q=queue.Queue();threading.Thread(target=lambda:[q.put(line) for line in p.stdout],daemon=True).start()
    def request(action,**fields):
        identifier=uuid.uuid4().hex;p.stdin.write(json.dumps({'action':action,'id':identifier,**fields})+'\n');p.stdin.flush()
        while True:
            line=q.get(timeout=120)
            try:value=json.loads(line)
            except ValueError:continue
            if value.get('id')==identifier:
                if not value.get('ok'):raise RuntimeError(json.dumps(value,ensure_ascii=False))
                return value['result']
    try:
        manifest=json.loads((ROOT/'music_demo/manifest.json').read_text(encoding='utf8'))
        tracks=[{**t,'file':str(ROOT/t['file'])} for t in manifest['tracks'] if t['group']=='library']
        imported=request('import',tracks=tracks);assert imported['total']==5
        wav=ROOT/'runs/20261114T194314_229002_music_microphone_development/clip_01/first/audio.wav'
        results=[request('match',wav=str(wav),mode='offline') for _ in range(2)]
        assert all(x['matched'] and x['title']=='Carefree' and x['artist']=='Kevin MacLeod' for x in results)
        p.stdin.close();p.wait(timeout=20);assert p.returncode==0
        from music_store import MusicStore
        store=MusicStore(r.path/'userdata/music');assert len(store.history())==2
        for _ in range(2):store.favourite(results[0]['song_id'])
        with store.db() as c:assert c.execute('SELECT count(*) FROM favourites').fetchone()[0]==1
        calls=[]
        for log in (r.path/'userdata/runs').glob('*/actions.jsonl'):
            calls += [json.loads(line) for line in log.read_text(encoding='utf8').splitlines() if 'audiotag_request' in line]
        assert not calls
        result={'evidence_kind':'actual_packaged_EXE_with_real_board_saved_WAV','exe_sha256':sha256(exe),'no_Python_or_Vivado_in_PATH':True,
            'windowed_process_pipe_works':True,'imported_tracks':5,'offline_matches':2,'history':2,'favourites':1,'AudioTag_requests':0,
            'not_live_USB_or_physical_BTNC_test':True,'results':results}
        write_json(r.path/'result.json',result);r.status('MUSIC5_packaged','passed','单EXE独立工作进程建库、真实板端WAV离线识别和持久化通过；尚需实时UI与中键实板验收',
            [str((r.path/'result.json').relative_to(ROOT))],'启动实时界面并进入集中手机验收');print(r.run_id)
    finally:
        if p.poll() is None:p.terminate();p.wait(timeout=10)
        r.manifest()
