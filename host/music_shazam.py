"""Board application's ShazamIO provider. Legacy AudioTag rows are read-only."""
import hashlib
import importlib
import json
import math
from pathlib import Path
import time

from audit import now,sha256,write_json
from app_paths import app_command
from music_store import MusicStore
from pc_shazam_backend import ShazamClient,versions,SHAZAMIO_VERSION,CORE_VERSION
from songrec_probe import center_clip,song_identity


MESSAGES={
    'offline_only':'当前为仅离线模式。',
    'online_not_found':'Shazam 在线曲库未匹配。',
    'online_timeout':'Shazam 请求超时，原录音已保存，可稍后手动重试。',
    'online_rate_limited':'Shazam 暂时限流，后续请求将等待冷却。',
    'online_error':'Shazam 在线服务未完成识别，原录音已保存。',
    'audio_prepare_failed':'无法准备有效的12秒识别片段，原录音已保留。',
    'online_interrupted':'上次识别进程中断，未自动重发；可手动重试原录音。',
    'legacy_online_task':'此任务属于旧AudioTag记录，已保留；新版可手动重新识别原录音。',
    'job_audio_mismatch':'任务与原录音校验不一致，未发起识别。',
}


def same_song(result,expected):
    return bool(result.get('matched') and song_identity(result.get('title',''),result.get('artist',''))==
                song_identity(expected.get('title',''),expected.get('artist','')))


def main_worker_command(clip,directory):
    return app_command('--internal-shazam',clip,directory)


class ShazamOnlineClient:
    def __init__(self,store=None,*,audit=None,client=None):
        self.store=store or MusicStore()
        self.audit=audit or (lambda *args,**kwargs:None)
        self.client=client or ShazamClient(command=main_worker_command)
        self.client.on_wait=lambda seconds:self.audit('shazam_wait',seconds=seconds)

    @staticmethod
    def failure(reason,**extra):
        return {'matched':False,'source':'none','provider':'shazamio','reason':reason,
                'message':MESSAGES.get(reason,MESSAGES['online_error']),**extra}

    def verify(self):
        try:
            importlib.import_module('shazamio');importlib.import_module('shazamio_core')
            stack=versions()
            ok=stack['shazamio']==SHAZAMIO_VERSION and stack['shazamio-core']==CORE_VERSION
            return {'ok':ok,'provider':'shazamio','versions':stack,'network_requests':0,
                    'message':'ShazamIO识曲组件可用，无需API Key；本次未发送音频。' if ok else 'ShazamIO组件版本不符合预期。'}
        except Exception as error:
            return {'ok':False,'provider':'shazamio','error_type':type(error).__name__,
                    'message':'ShazamIO组件未能载入，请使用完整的新版EXE。','network_requests':0}

    def recognize(self,identifier,wav,mode='auto'):
        if mode=='offline':return self.failure('offline_only')
        wav=Path(wav);wav_hash=sha256(wav)
        previous=self.store.online(identifier)
        if previous:
            details=json.loads(previous['details'])
            if details.get('provider')!='shazamio':return self.failure('legacy_online_task')
            if previous['wav_sha256']!=wav_hash:return self.failure('job_audio_mismatch')
            if previous['status']=='done' and isinstance(details.get('result'),dict):
                return {**details['result'],'cached_original_task':True}
            return self.failure('online_interrupted')
        directory=self.store.folder/'shazam'/hashlib.sha256(str(identifier).encode('utf8')).hexdigest()[:32]
        directory.mkdir(parents=True,exist_ok=True)
        details={'provider':'shazamio','source_wav':str(wav),'source_sha256':wav_hash,'directory':str(directory)}
        try:
            prep=center_clip(wav,directory/'center_12s.wav')
        except (OSError,ValueError,EOFError) as error:
            result=self.failure('audio_prepare_failed',error_type=type(error).__name__)
            details['result']=result
            self.store.save_online(identifier,wav_hash,'done',details=details)
            return result
        details['preprocessing']=prep
        self.store.save_online(identifier,wav_hash,'running',details=details)
        ready=self.store.setting('shazam_next_allowed_at',0)
        if not isinstance(ready,(int,float)) or not math.isfinite(ready):ready=0
        earliest=max(time.time(),ready)
        self.client.next_allowed=max(getattr(self.client,'next_allowed',0),time.monotonic()+max(0,earliest-time.time()))
        self.store.set_setting('shazam_next_allowed_at',earliest+30)
        self.audit('shazam_request',job_id=identifier,clip_sha256=prep['clip_sha256'],sample_rate=prep['sample_rate'])
        try:
            native=self.client.recognize(directory/'center_12s.wav',directory)
        except Exception as error:
            native={'matched':False,'status':'worker_error','error_type':type(error).__name__}
        reason={'not_found':'online_not_found','timeout':'online_timeout','rate_limited':'online_rate_limited',
                'invalid_audio':'audio_prepare_failed'}.get(native.get('status'),'online_error')
        if native.get('matched'):
            result={**native,'source':'shazamio','provider':'shazamio','reason':'matched'}
        else:
            result={**native,**self.failure(reason)}
        result.update(preprocessing=prep,online_elapsed_s=native.get('elapsed_s'),recognized_at=native.get('recognized_at',now()),
                      cost_yuan=0,paid_service_calls=0,key_accesses=0,AudioTag_calls=0)
        if native.get('status')=='rate_limited':
            self.store.set_setting('shazam_next_allowed_at',time.time()+max(60,native.get('retry_after_s',0)))
        details['result']=result
        write_json(directory/'main_result.json',result)
        self.store.save_online(identifier,wav_hash,'done',details=details)
        self.audit('shazam_completed',job_id=identifier,matched=result['matched'],status=native.get('status'),
                   http_requests=native.get('http_requests',0))
        return result
