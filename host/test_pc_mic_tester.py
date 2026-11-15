"""PC-only orchestration tests: simulated API, real WAVs, no board imports."""
import json,tempfile,wave,sys
from pathlib import Path
from unittest.mock import patch
import numpy as np
import audit,pc_mic_backend as backend
from audit import ROOT,Run,write_json
from music_online import AudioTagClient
from pc_mic_backend import Backend,validate_wav,redact
from pc_mic_capture import audio_metrics


class Fake:
    def __init__(self):self.actions=[]
    def post(self,action,key,**kwargs):
        self.actions.append(action)
        if action=='stat':return {'success':True,'current_credit_balance':0,'credits_spent':0,'identification_free_sec_remainder':100}
        if action=='identify':return {'success':True,'token':'SIMULATED-TOKEN-PRIVATE','apikey':key}
        return {'success':True,'result':'found','data':[{'confidence':9,'tracks':[['Example song','Example artist']]}]}


def test():
    run=Run('pc_mic_tester_tests');checks=[]
    assert not any(x in sys.modules for x in ('serial','protocol','music_board','monitor_service'))
    with tempfile.TemporaryDirectory() as tmp:
        folder=Path(tmp);wav=folder/'input.wav';samples=(np.sin(np.arange(320000)*2*np.pi*440/16000)*4000).astype('<i2')
        with wave.open(str(wav),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(samples.tobytes())
        meta=validate_wav(wav);assert meta['duration_s']==20 and meta['samples']==320000
        fake=Fake();events=[]
        def client(store,**kwargs):return AudioTagClient(store,**kwargs,key_provider=lambda:'SIMULATED-KEY-PRIVATE',confirmed=True,poll_interval=0,poll_limit=1)
        with patch.object(audit,'ROOT',folder),patch.object(backend,'ROOT',folder),patch.object(backend,'reuse_account_confirmation',lambda:None):
            engine=Backend(lambda kind,**fields:events.append((kind,fields)),transport_factory=lambda:fake,client_factory=client)
            trial,job=engine.new_trial();result=engine.recognize(trial,job,wav,{**meta,'source':'synthetic_test_fixture'})
            assert result['service_status']=='found' and result['result']['title']=='Example song'
            assert result['candidates'][0]['confidence']==9 and result['result']['zero_cost_verified']
            assert fake.actions==['stat','identify','get_result','stat']
            assert result['no_local_matcher'] and result['no_board_connection']
            engine.recognize(trial,job,wav,meta);assert fake.actions.count('identify')==1
            assert len(engine.store.history())==1
            before=list(fake.actions)
            try:engine.recognize(trial,job,wav,{**meta,'complete':False})
            except ValueError:pass
            else:raise AssertionError('Incomplete capture must not reach HTTP')
            assert fake.actions==before
            for path in trial.path.glob('api_*.json'):
                text=path.read_text(encoding='utf8');assert 'SIMULATED-KEY-PRIVATE' not in text and 'SIMULATED-TOKEN-PRIVATE' not in text
            assert any(e[0]=='stage' for e in events)
        safe=redact({'apikey':'secret','token':'private', 'secret':{'label':'SECRET'}},'secret')
        assert 'secret' not in json.dumps(safe).casefold() and 'private' not in json.dumps(safe)
        assert audio_metrics(samples.tobytes())['clipped_samples']==0
        checks=['PC-only imports','20_second_PCM16_WAV','same_guarded_API_pipeline','server_found_and_candidates_separate_from_parser',
            'single_upload_and_one_history_row','incomplete_recording_never_uploaded','key_and_token_redacted_in_saved_service_responses','progress_events']
    write_json(run.path/'result.json',{'passed':True,'evidence_kind':'simulated_API_with_synthetic_WAV','checks':checks,'real_API_requests':0})
    run.manifest();print(run.run_id)


if __name__=='__main__':test()
