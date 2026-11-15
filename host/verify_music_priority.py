"""Exercise new policy against the real free API using an archived board WAV."""
import json,time,uuid
from pathlib import Path
from audit import ROOT,Run,write_json,sha256,now
from music_store import MusicStore
from music_library import LocalMatcher
from music_online import AudioTagClient
from music_worker import recognize_recording

def main():
    run=Run('music_online_priority_real');run.snapshot('用户改为API优先；复用已校验20秒实板WAV验证真实请求顺序，不重复要求放歌')
    pilot=sorted((ROOT/'runs').glob('*music_exe_gui_pilot/result.json'))[-1]
    original=json.loads(pilot.read_text(encoding='utf8'));meta=original['metadata'];wav=Path(meta['wav'])
    assert sha256(wav)==meta['wav_sha256'] and meta['source']=='board_microphone'
    class Matcher:
        def __init__(self):self.calls=0
        def match(self,path):self.calls+=1;run.event('local_fallback_started',wav_sha256=sha256(path));return LocalMatcher().match(path)
    store=MusicStore(run.path/'isolated_store');matcher=Matcher();requests=[]
    def audit(kind,**fields):
        if kind=='audiotag_request':requests.append(fields['action'])
        run.event(kind,**fields)
    start=time.perf_counter();result,local=recognize_recording(uuid.uuid4().hex,wav,'auto',store,matcher,online=AudioTagClient(store,audit=audit))
    data={'run_id':run.run_id,'time':now(),'evidence_kind':'real_official_API_and_archived_real_board_WAV',
          'input_pilot_run_id':pilot.parent.name,'metadata':meta,'requests':requests,'local_match_calls':matcher.calls,
          'expected':{'title':'Take It Easy','artist':'Eagles'},'elapsed_s':time.perf_counter()-start,'result':result,
          'one_upload':requests.count('identify')<=1,'api_first':requests[0]=='stat' if requests else False}
    write_json(run.path/'result.json',data);write_json(ROOT/'state/music_api_priority.json',data)
    run.event('real_online_priority_verified',requests=requests,matched=result['matched'],source=result.get('source'),local_calls=matcher.calls)
    run.manifest();print(json.dumps({k:data[k] for k in ('run_id','requests','local_match_calls','elapsed_s')}));print(json.dumps({k:result.get(k) for k in ('matched','source','title','artist','reason','before','after','zero_cost_verified','cost_yuan')},ensure_ascii=False))
if __name__=='__main__':main()
