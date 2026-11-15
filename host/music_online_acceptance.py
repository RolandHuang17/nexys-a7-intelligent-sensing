"""Three real board WAVs: local miss -> free stat -> one upload -> token result."""
import json,uuid,re
from pathlib import Path
from audit import ROOT,Run,write_json,sha256
from music_store import MusicStore
from music_library import LocalMatcher
from music_online import AudioTagClient
from music_worker import recognize_recording

def fold(value):return ''.join(c for c in value.casefold() if c.isalnum())

if __name__=='__main__':
    r=Run('music_online_physical');store=MusicStore();matcher=LocalMatcher();rows=[]
    state=json.loads((ROOT/'state/music_development.json').read_text(encoding='utf8'));source=ROOT/'runs'/state['run_id']/'result.json'
    data=json.loads(source.read_text(encoding='utf8'));tracks=[x for x in data['trials'] if x['track'].get('group')=='development_negative'];assert len(tracks)==3
    for clip in tracks:
        wav=Path(clip['metadata']['wav']);assert sha256(wav)==clip['metadata']['wav_sha256'];assert clip['metadata']['source']=='board_microphone'
        identifier=uuid.uuid4().hex;calls=[]
        def event(kind,**fields):
            r.event(kind,**fields)
            if kind=='audiotag_request':calls.append(fields['action'])
        client=AudioTagClient(store,audit=event)
        result,local=recognize_recording(identifier,wav,'auto',store,matcher,online=client,metadata=clip['metadata'])
        expected=clip['track'];correct=bool(result.get('matched') and fold(result.get('title',''))==fold(expected['title']) and fold(expected['artist']) in fold(result.get('artist','')))
        row={'job_id':identifier,'expected':{k:expected[k] for k in ('title','artist','source_url','license_page')},
            'source_run_id':state['run_id'],'board_metadata':clip['metadata'],'local':local,'requests':calls,'result':result,'correct':correct,
            'evidence_kind':'real_AudioTag_API_and_real_board_microphone_laptop_speaker','one_automatic_upload':calls.count('identify')<=1}
        rows.append(row);write_json(r.path/f'trial_{len(rows):02}.json',row)
        print(json.dumps({'trial':len(rows),'expected':expected['title'],'matched':result.get('matched'),'title':result.get('title'),'artist':result.get('artist'),
            'reason':result.get('reason'),'correct':correct,'before':result.get('before'),'after':result.get('after'),'requests':calls},ensure_ascii=False),flush=True)
    summary={'source':'real_board_WAV_and_official_API','run_id':r.run_id,'trials':rows,'correct':sum(x['correct'] for x in rows),'total':len(rows),
        'actual_cost_yuan':0 if all(x['result'].get('cost_yuan')==0 for x in rows) else None,'target_met':sum(x['correct'] for x in rows)>=2}
    write_json(r.path/'result.json',summary);write_json(ROOT/'state/music_online_acceptance.json',summary)
    passed=summary['target_met'] and summary['actual_cost_yuan']==0
    r.status('MUSIC4_online','passed' if passed else 'failed','真实在线目标达成且费用零' if passed else '实际结果已保留，尚未达到在线目标',
        [str((r.path/'result.json').relative_to(ROOT))],'继续正式手机外放与原功能回归');r.manifest();print('RUN_ID='+r.run_id)
