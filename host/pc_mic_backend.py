"""AudioTag-only PC microphone trials, isolated from all board state."""
import base64,json,re,time,uuid,wave
from pathlib import Path
from urllib.parse import quote
from audit import ROOT,Run,now,sha256,write_json
from music_online import AudioTagClient,RequestsTransport,online_song_identity
from music_store import MusicStore

PC_MIC_VERSION='1.0.0'


def reuse_account_confirmation():
    import os,shutil
    target=ROOT/'state/music_account_attestation.json'
    if target.exists():return
    local=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))
    for source in (local/'NexysMonitor/state/music_account_attestation.json',Path.cwd()/'state/music_account_attestation.json'):
        if source.exists() and json.loads(source.read_text(encoding='utf8')).get('free_only_confirmed_by_user') is True:
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);return


def redact(value,key):
    if isinstance(value,dict):
        return {redact(str(k),key):'[REDACTED]' if str(k).casefold() in ('token','apikey','api_key','authorization','password') else redact(v,key) for k,v in value.items()}
    if isinstance(value,list):return [redact(v,key) for v in value]
    if isinstance(value,str):
        for secret in (key,quote(key,safe=''),base64.b64encode(key.encode()).decode()):
            if secret:value=re.sub(re.escape(secret),'[REDACTED]',value,flags=re.IGNORECASE)
        return value
    return value


class DiagnosticTransport:
    def __init__(self,run,publish,delegate=None):
        self.run=run;self.publish=publish;self.delegate=delegate or RequestsTransport();self.counts={};self.last_service={}
    def post(self,action,key,**kwargs):
        stage={'stat':'核对免费额度与零费用','identify':'向AudioTag上传本次录音（仅一次）','get_result':'查询AudioTag原任务结果'}[action]
        self.publish('stage',text=stage)
        reply=self.delegate.post(action,key,**kwargs)
        self.counts[action]=self.counts.get(action,0)+1
        safe=redact(reply,key);write_json(self.run.path/f'api_{action}_{self.counts[action]:03}.json',safe)
        if action=='get_result':self.last_service=safe
        # The token stays in the client's local task store, never in diagnostics.
        usable=dict(safe)
        if 'token' in reply:usable['token']=reply['token']
        return usable


def unique_candidates(result):
    found={}
    for row in result.get('candidates',[]):
        identity=online_song_identity(row['title'],row['artist']);old=found.get(identity)
        if old is None or row['confidence']>old['confidence']:found[identity]=row
    return sorted(found.values(),key=lambda row:-row['confidence'])


class Backend:
    def __init__(self,publish,*,transport_factory=None,client_factory=AudioTagClient):
        self.publish=publish;self.store=MusicStore(ROOT/'api_store');self.transport_factory=transport_factory;self.client_factory=client_factory
        reuse_account_confirmation()
    def new_trial(self,source='computer_microphone'):
        run=Run('pc_mic_api_trial');identifier=uuid.uuid4().hex
        job={'id':identifier,'run_id':run.run_id,'directory':str(run.path),'source':source,'started_at':now(),'app_version':PC_MIC_VERSION,'status':'created'}
        write_json(run.path/'trial.json',job);return run,job
    def recognize(self,run,job,wav,metadata=None):
        wav=Path(wav)
        if metadata is not None and not metadata.get('complete',False):raise ValueError('录音未完整结束，未调用API')
        before_calls=[]
        def audit(kind,**fields):
            run.event(kind,**fields)
            if kind=='audiotag_request':before_calls.append(fields['action'])
        transport=DiagnosticTransport(run,self.publish,self.transport_factory() if self.transport_factory else None)
        client=self.client_factory(self.store,transport=transport,audit=audit)
        job.update(wav=str(wav),wav_sha256=sha256(wav),metadata=metadata,status='matching');write_json(run.path/'trial.json',job)
        started=time.monotonic();result=client.recognize(job['id'],wav,'auto');elapsed=time.monotonic()-started
        previous=self.store.online(job['id'])
        self.store.record_result(job['id'],result,'auto',wav,sha256(wav),{'input_source':job['source'],'pc_mic_metadata':metadata},update_pending=True)
        record={**job,'finished_at':now(),'status':'complete' if previous and previous['status']=='done' else 'attention',
            'result':result,'service_status':transport.last_service.get('result'),
            'candidates':unique_candidates(result),'API_actions_this_call':before_calls,'recognition_wall_s':elapsed,
            'one_upload_this_call':before_calls.count('identify')<=1,'no_local_matcher':True,'no_board_connection':True,
            'pending_query_available':bool(previous and previous.get('token') and previous['status']=='submitted')}
        write_json(run.path/'result.json',record);write_json(ROOT/'latest.json',record)
        run.event('pc_mic_trial_completed',job_id=job['id'],service_status=record['service_status'],matched=result['matched'],reason=result.get('reason'),
            zero_cost_verified=result.get('zero_cost_verified'),identify_calls=before_calls.count('identify'))
        run.manifest();return record
    def verify(self):
        run=Run('pc_mic_account_check');result=self.client_factory(self.store,audit=run.event).verify()
        write_json(run.path/'result.json',result);run.manifest();return result
    def pending(self):return self.store.pending_online()


def validate_wav(path):
    with wave.open(str(path),'rb') as wav:
        if (wav.getnchannels(),wav.getsampwidth())!=(1,2) or wav.getframerate() not in (8000,16000):
            raise ValueError('对照片段需要8或16kHz、单声道PCM16 WAV；不会改动原文件')
        seconds=wav.getnframes()/wav.getframerate()
        if not 15<=seconds<=60:raise ValueError('请选择15至60秒的完整WAV对照片段')
        return {'source':'imported_clean_WAV_reference_not_microphone','complete':True,'sample_rate':wav.getframerate(),
                'samples':wav.getnframes(),'duration_s':seconds,'wav':str(path)}
