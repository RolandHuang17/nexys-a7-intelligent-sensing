"""Opt-in network regression of the frozen main worker using three real board WAVs.

Without --execute-online this only validates inputs and prints the replay plan.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import wave


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--execute-online',action='store_true')
    parser.add_argument('--baseline-report',type=Path,default=Path(
        r'D:\projects\2222wuxiaoping_codex\nexys-event-recorder\state\shazam_main_verification.json'))
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    candidate=json.loads((root/'state/shazam_main_candidate.json').read_text(encoding='utf8'))
    frozen=json.loads((root/'docs/UI冻结验证.json').read_text(encoding='utf8'))
    exe=Path(candidate['candidate_exe'])
    assert sha(exe)==candidate['exe_sha256']==frozen['exe_sha256']
    previous=json.loads(args.baseline_report.read_text(encoding='utf8'))
    rows=previous['rows'];assert len(rows)==3
    plan=[]
    for row in rows:
        wav=Path(row['original_wav']);assert sha(wav)==row['wav_sha256']
        with wave.open(str(wav),'rb') as audio:
            assert (audio.getframerate(),audio.getnchannels(),audio.getsampwidth(),audio.getnframes())==(8000,1,2,160000)
        plan.append({k:row[k] for k in ('title','artist','original_wav','wav_sha256')})
    prepared={'kind':'frozen_main_worker_replay_of_archived_real_board_microphone_recordings',
        'exe_sha256':sha(exe),'app_version':'1.3.0','new_live_phone_recordings':False,
        'recordings':plan,'requests':3,'automatic_HTTP_retries':0,
        'minimum_spacing_s':30,'purpose':'UI migration frozen worker compatibility regression'}
    if not args.execute_online:
        write(root/'docs/UI在线回放计划.json',prepared)
        print(json.dumps({'status':'prepared_no_network','plan':prepared},ensure_ascii=False));return
    sys.path.insert(0,str(root/'host'))
    from music_shazam import same_song
    folder=root/'runs'/('ui_online_replay_'+uuid.uuid4().hex[:10]);folder.mkdir(parents=True)
    data=folder/'user_data'
    env={**os.environ,'NEXYS_MONITOR_DATA':str(data),'NEXYS_PORTABLE_RUNTIME':'1'}
    report={**prepared,'status':'running','started_at':datetime.now().astimezone().isoformat(),
        'data_root':str(data),'rows':[]}
    write(folder/'result.json',report)
    process=subprocess.Popen([str(exe),'--internal-music-worker'],env=env,
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8',
        creationflags=subprocess.CREATE_NO_WINDOW)
    messages=queue.Queue()
    def stdout():
        for line in process.stdout:
            try:messages.put(json.loads(line))
            except ValueError:messages.put({'invalid_line':line[:200]})
    def stderr():
        with (folder/'worker.stderr.txt').open('w',encoding='utf8') as log:
            for line in process.stderr:log.write(line)
    threading.Thread(target=stdout,daemon=True).start();threading.Thread(target=stderr,daemon=True).start()
    def request(action,**values):
        identifier=uuid.uuid4().hex
        process.stdin.write(json.dumps({'id':identifier,'action':action,**values},ensure_ascii=False)+'\n');process.stdin.flush()
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            try:item=messages.get(timeout=min(1,max(.1,deadline-time.monotonic())))
            except queue.Empty:
                if process.poll() is not None:raise RuntimeError('Frozen worker exited before response')
                continue
            with (folder/'worker_messages.jsonl').open('a',encoding='utf8') as log:
                log.write(json.dumps(item,ensure_ascii=False)+'\n')
            if item.get('id')==identifier and item.get('action')==action:
                assert item.get('ok'),item
                return item['result']
        raise TimeoutError('Frozen worker response deadline')
    try:
        component=request('verify',mode='auto');assert component['ok'] and component['network_requests']==0
        report['component_check']=component
        for row in plan:
            result=request('match',wav=row['original_wav'],mode='auto',game=False,
                metadata={'validation_replay':True,'new_live_recording':False,'original_wav_sha256':row['wav_sha256']})
            assert sha(row['original_wav'])==row['wav_sha256']
            verified={**row,'result':result,'correct_online':same_song(result,row) and result.get('source')=='shazamio'}
            report['rows'].append(verified);write(folder/'result.json',report)
            print(json.dumps({'song':row['title'],'correct':verified['correct_online'],
                'source':result.get('source'),'reason':result.get('reason')},ensure_ascii=False),flush=True)
    except Exception as error:
        report.update(status='failed',error_type=type(error).__name__)
        write(folder/'result.json',report);raise
    finally:
        process.stdin.close()
        try:process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            import psutil
            try:owned=psutil.Process(process.pid).children(recursive=True)
            except psutil.NoSuchProcess:owned=[]
            for child in reversed(owned):
                try:child.kill()
                except psutil.NoSuchProcess:pass
            process.kill();process.wait(timeout=10)
    matched=sum(r['correct_online'] for r in report['rows'])
    with sqlite3.connect('file:'+(data/'music/music.sqlite3').as_posix()+'?mode=ro',uri=True) as db:
        history=db.execute("SELECT COUNT(*) FROM history WHERE source='shazamio'").fetchone()[0]
    report.update(status='passed' if matched==3 and history==3 else 'failed',correct=matched,total=len(report['rows']),
        Shazam_history_rows=history,finished_at=datetime.now().astimezone().isoformat())
    write(folder/'result.json',report);write(root/'docs/UI在线回放验证.json',report)
    print(json.dumps({'status':report['status'],'correct':matched,'total':len(report['rows']),
        'report':str(folder/'result.json')},ensure_ascii=False),flush=True)
    assert report['status']=='passed'


if __name__=='__main__':main()
