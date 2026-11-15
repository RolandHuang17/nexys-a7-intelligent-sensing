"""Online preparation and restart recovery with a simulated HTTP transport."""
import json,tempfile,uuid,wave
from pathlib import Path
import numpy as np
from audit import Run,write_json,sha256
from music_upload import prepare_upload
from music_store import MusicStore
from music_online import AudioTagClient
from music_worker import recognize_recording
from test_music_software import Fake


def test():
    r=Run('music_api_tests');checks=[]
    with tempfile.TemporaryDirectory() as tmp:
        folder=Path(tmp);wav=folder/'board.wav'
        a=(1008+70*np.sin(np.arange(160000)*2*np.pi*440/8000)).astype('<i2');a[8000]=8000
        with wave.open(str(wav),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(8000);w.writeframes(a.tobytes())
        before=sha256(wav);meta=prepare_upload(wav,folder/'upload.wav')
        with wave.open(str(folder/'upload.wav'),'rb') as w:
            assert (w.getframerate(),w.getnframes(),w.getnchannels(),w.getsampwidth())==(8000,160000,1,2)
        assert sha256(wav)==before and meta['cropped'] is False
        assert meta['upload_rms_dbfs']>-20 and meta['limited_fraction']<.002
        checks.append('whole_20_second_recording_preserved_and_knock_does_not_reduce_song_level')
        class TimeoutOnce(Fake):
            def __init__(self):super().__init__();self.failed=False
            def post(self,action,key,**values):
                if action=='get_result' and not self.failed:
                    self.calls.append(action);self.failed=True;raise TimeoutError('simulated response loss')
                return super().post(action,key,**values)
        store=MusicStore(folder/'user');fake=TimeoutOnce();identifier=uuid.uuid4().hex
        class NoMatch:
            def match(self,path):return {'matched':False,'source':'none'}
        client=AudioTagClient(store,fake,lambda:'SIMULATED-SECRET',True,poll_interval=0,poll_limit=1)
        first,_=recognize_recording(identifier,wav,'auto',store,NoMatch(),online=client)
        assert first['reason']=='online_timeout' and first['can_resume']
        assert store.setting('online_locked') is True and len(store.history())==1
        assert store.pending_online()==[{'job_id':identifier,'wav':str(wav)}]
        # Reopen the actual database to simulate a worker/application restart.
        restored=MusicStore(folder/'user');client=AudioTagClient(restored,fake,lambda:'SIMULATED-SECRET',True,poll_interval=0,poll_limit=1)
        final,_=recognize_recording(identifier,wav,'auto',restored,NoMatch(),online=client)
        assert final['matched'] and final['source']=='audiotag' and final['cost_yuan']==0
        assert fake.calls==['stat','identify','get_result','get_result','stat']
        assert len(restored.history())==1 and restored.history()[0]['source']=='audiotag'
        assert restored.pending_online()==[] and restored.setting('online_locked') is False
        checks.append('timeout_and_worker_restart_resume_original_token_with_one_upload_and_one_final_history_row')
        wrong=folder/'wrong.wav';wrong.write_bytes(wav.read_bytes()+b'changed')
        before_calls=list(fake.calls);assert client.recognize(identifier,wrong)['matched'] is False
        assert fake.calls==before_calls;checks.append('wrong_recording_cannot_be_attached_to_existing_online_task')
        for bad in (None,'99',float('nan'),float('inf'),-1,101,True):
            assert not AudioTagClient.result({'result':'found','data':[{'confidence':bad,'tracks':[['Song','Artist']]}]},'SIMULATED-SECRET')['matched']
        checks.append('malformed_service_confidence_rejected_without_crashing')
        release_variants={'result':'found','data':[{'confidence':99,'tracks':[
            ['Take It Easy','Eagles'],['Take It Easy (Single Version) [Remastered] (Single Version)','Eagles']]}]}
        resolved=AudioTagClient.result(release_variants,'SIMULATED-SECRET')
        assert resolved['matched'] and resolved['title']=='Take It Easy' and len(resolved['candidates'])==2
        for different in ('Another song','Take It Easy (Live)','Take It Easy (Remix)'):
            reply={'result':'found','data':[{'confidence':99,'tracks':[['Take It Easy','Eagles'],[different,'Eagles']]}]}
            assert AudioTagClient.result(reply,'SIMULATED-SECRET')['reason']=='ambiguous_online'
        checks.append('same_song_release_labels_merge_but_different_song_live_and_remix_remain_ambiguous')
    write_json(r.path/'result.json',{'passed':True,'evidence_kind':'simulated_API_and_real_local_audio_processing','checks':checks,'real_AudioTag_requests':0})
    r.manifest();print(r.run_id)


if __name__=='__main__':test()
