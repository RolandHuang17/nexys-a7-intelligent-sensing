"""AudioTag free-only guard. No paid endpoints and no automatic upload retry."""
import hashlib,json,math,time,wave,re,base64,urllib.parse
from pathlib import Path
from audit import ROOT,now
from music_credentials import load_key
from music_store import MusicStore,song_key

STAT_FIELDS=('current_credit_balance','identification_free_sec_remainder','credits_spent','queries_count','uploaded_duration_sec','uploaded_size_bytes')
REASONS={'no_key':'未配置AudioTag密钥','account_unconfirmed':'尚未确认纯免费账户','paid_account':'账户存在付费积分或付费使用记录',
 'insufficient_free':'在线免费额度不足','quota_unknown':'无法确认在线免费额度','offline':'当前网络不可用','upload_unknown':'提交状态未知，已保留录音，请勿重复自动提交',
 'online_timeout':'在线任务尚未完成，可继续查询原任务','online_not_found':'在线曲库未匹配',
 'ambiguous_online':'在线返回多个候选，暂不确定歌名','online_error':'在线服务未能完成识别','audio_prepare_failed':'在线音频格式准备失败，原录音已保留','verification_pending':'免费用量后置核验未完成，在线提交已暂停'}
def online_song_identity(title,artist):
    """Only merge explicit release labels, retaining live/remix/different titles."""
    title=' '.join(title.casefold().split())
    version=r'(?:(?:19|20)\d{2}\s+)?remaster(?:ed)?(?:\s+(?:19|20)\d{2})?|single version|album version'
    while True:
        bracket=re.search(r'\s*[\[(]([^\[\]()]+)[\])]\s*$',title)
        if bracket and re.fullmatch(version,bracket[1].strip()):title=title[:bracket.start()].strip();continue
        dash=re.search(r'\s+-\s+('+version+r')\s*$',title)
        if dash:title=title[:dash.start()].strip();continue
        break
    return song_key(title,artist)


class RequestsTransport:
    def __init__(self):
        import requests
        self.session=requests.Session()
        self.session.mount('https://',requests.adapters.HTTPAdapter(max_retries=0))
    def post(self,action,key,*,wav=None,token=None):
        import requests
        fields={'action':action,'apikey':key}
        if token:fields['token']=token
        try:
            if wav:
                with Path(wav).open('rb') as f:r=self.session.post('https://audiotag.info/api',data=fields,files={'file':('recording.wav',f,'audio/wav')},timeout=(5,30),allow_redirects=False)
            else:r=self.session.post('https://audiotag.info/api',data=fields,timeout=(5,15),allow_redirects=False)
            if r.status_code!=200:raise RuntimeError('service_response')
            value=r.json()
            if not isinstance(value,dict):raise RuntimeError('service_format')
            return value
        except requests.ConnectionError:raise ConnectionError('network_unavailable') from None
        except requests.Timeout:raise TimeoutError('request_timeout') from None
        except Exception:raise RuntimeError('service_response_invalid') from None

class AudioTagClient:
    def __init__(self,store=None,transport=None,key_provider=load_key,confirmed=None,audit=None,poll_interval=1,poll_limit=90):
        self.store=store or MusicStore();self.transport=transport;self.key_provider=key_provider;self.confirmed=confirmed
        self.audit=audit or (lambda *a,**k:None);self.poll_interval=poll_interval;self.poll_limit=poll_limit;self.last_error=None
    def attested(self):
        if self.confirmed is not None:return self.confirmed
        try:return json.loads((ROOT/'state/music_account_attestation.json').read_text(encoding='utf8')).get('free_only_confirmed_by_user') is True
        except (OSError,ValueError):return False
    def call(self,action,key,**kwargs):
        if action not in ('stat','identify','get_result'):raise ValueError('不支持此接口')
        if self.transport is None:self.transport=RequestsTransport()
        self.audit('audiotag_request',action=action,uploads_audio=action=='identify')
        reply=self.transport.post(action,key,**kwargs)
        known_errors=('invalid command or parameter','api key expired','api key inactive','api key unrecognized','api key invalid or empty',
            'service temporarily not available','internal error: no server response','internal error: server init error',
            'credit balance exhausted','no audio found, format invalid or unsupported','audio duration is too short',
            'credit balance insufficient or exhausted','internal error: could not communicate to the recognition server',
            'internal error: could not process the file','no recognition result found for the token','internal error: server recognition error','internal error: server is not ready')
        error=reply.get('error');safe_error=None
        if isinstance(error,str) and error:
            safe_error=error
            for secret in (key,base64.b64encode(key.encode()).decode(),urllib.parse.quote(key,safe='')):
                safe_error=re.sub(re.escape(secret),'[REDACTED]',safe_error,flags=re.IGNORECASE)
            safe_error=re.sub(r'[\w.+-]+@[\w.-]+','[EMAIL]',safe_error)
            safe_error=re.sub(r'[a-fA-F0-9]{16,}','[IDENTIFIER]',safe_error)[:240]
        self.last_error=safe_error
        self.audit('audiotag_reply_summary',action=action,success=reply.get('success') is True,error_category=safe_error,
            token_present=isinstance(reply.get('token'),str) and bool(reply.get('token')),job_status=reply.get('job_status') if reply.get('job_status') in ('wait','found','not found') else None)
        return reply
    def stats(self,key):
        raw=self.call('stat',key)
        if raw.get('success') is not True:raise ValueError('quota_unknown')
        out={k:raw.get(k) for k in STAT_FIELDS}
        for keyname in ('current_credit_balance','identification_free_sec_remainder','credits_spent'):
            v=out[keyname]
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0:raise ValueError('quota_unknown')
        return out
    def check(self,key,seconds):
        try:s=self.stats(key)
        except ConnectionError:return None,'offline'
        except Exception:return None,'quota_unknown'
        if s['current_credit_balance']!=0 or s['credits_spent']!=0:return s,'paid_account'
        if s['identification_free_sec_remainder']<math.ceil(seconds):return s,'insufficient_free'
        return s,None
    def verify(self):
        key=self.key_provider()
        if not key:return {'ok':False,'reason':'no_key'}
        if not self.attested():return {'ok':False,'reason':'account_unconfirmed'}
        stats,reason=self.check(key,0)
        if reason is None:self.store.set_setting('online_locked',False)
        self.audit('audiotag_account_checked',ok=reason is None,stats=stats,reason=reason)
        return {'ok':reason is None,'stats':stats,'reason':reason,'message':REASONS.get(reason,'免费账户检查通过')}
    def recognize(self,identifier,wav,mode='auto'):
        if mode!='auto':return self.failure('offline_only')
        key=self.key_provider()
        if not key:return self.failure('no_key')
        if not self.attested():return self.failure('account_unconfirmed')
        previous=self.store.online(identifier)
        if previous:
            if previous['wav_sha256']!=hashlib.sha256(Path(wav).read_bytes()).hexdigest():
                return {**self.failure('online_error'),'message':'任务与录音不一致，已停止查询；原文件保留。'}
            if previous['status']=='done':return json.loads(previous['details'])['result']
            if previous.get('token'):return self.poll(identifier,wav,key,previous['token'],json.loads(previous['details']))
            return self.failure('upload_unknown')
        if self.store.setting('online_locked',False):return self.failure('verification_pending')
        with wave.open(str(wav),'rb') as w:duration=w.getnframes()/w.getframerate()
        before,reason=self.check(key,duration)
        self.audit('audiotag_free_guard',job_id=identifier,seconds=duration,stats=before,allowed=reason is None,reason=reason)
        if reason:return self.failure(reason,before=before)
        wav_hash=hashlib.sha256(Path(wav).read_bytes()).hexdigest();details={'before':before,'seconds':duration,'wav_sha256':wav_hash,'source_wav':str(wav)}
        try:
            from music_upload import prepare_upload
            folder=self.store.folder/'uploads';folder.mkdir(exist_ok=True)
            upload=folder/(identifier+'_native8000.wav')
            preprocessing=prepare_upload(wav,upload)
            details.update(upload_wav=str(upload),upload_sha256=hashlib.sha256(upload.read_bytes()).hexdigest(),preprocessing=preprocessing)
            self.audit('audiotag_audio_prepared',job_id=identifier,source_wav_sha256=wav_hash,upload_sha256=details['upload_sha256'],seconds=duration,rate=8000,whole_recording=True)
        except Exception:return self.failure('audio_prepare_failed',before=before)
        # Commit before transmitting: a lost response/restart can never trigger automatic resubmission.
        self.store.save_online(identifier,wav_hash,'uploading',details=details)
        started=time.perf_counter()
        try:reply=self.call('identify',key,wav=upload)
        except Exception:
            self.store.save_online(identifier,wav_hash,'submission_unknown',details=details)
            self.store.set_setting('online_locked',True)
            return self.failure('upload_unknown',before=before)
        token=reply.get('token')
        if reply.get('success') is not True or not isinstance(token,str) or not token:
            service_error=self.last_error
            after=None
            try:after=self.stats(key)
            except Exception:pass
            verified=bool(after and after['current_credit_balance']==0 and after['credits_spent']==0)
            self.store.set_setting('online_locked',not verified)
            result=self.failure('online_error',before=before,after=after,service_error=service_error,zero_cost_verified=verified,cost_yuan=0 if verified else None)
            if service_error in ('audio is too short','audio duration is too short'):result['message']='在线服务认为录音太短，请下一次选择20秒。原录音已保留。'
            self.store.save_online(identifier,wav_hash,'rejected',details={**details,'result':result});return result
        details['request_started_monotonic']=started;details['request_started_wall']=time.time()
        self.store.save_online(identifier,wav_hash,'submitted',token=token,details=details)
        self.audit('audiotag_submitted',job_id=identifier,token_sha256=hashlib.sha256(token.encode()).hexdigest(),wav_sha256=wav_hash)
        return self.poll(identifier,wav,key,token,details)
    def poll(self,identifier,wav,key,token,details):
        deadline=time.monotonic()+self.poll_limit
        while time.monotonic()<deadline:
            try:reply=self.call('get_result',key,token=token)
            except Exception:
                self.store.set_setting('online_locked',True)
                return self.failure('online_timeout',before=details.get('before'),pending_job_id=identifier,can_resume=True)
            status=reply.get('result')
            if reply.get('success') is not True:
                self.store.set_setting('online_locked',True)
                return self.failure('online_error',before=details.get('before'),pending_job_id=identifier,can_resume=True)
            if status=='wait':time.sleep(self.poll_interval);continue
            finished=time.perf_counter_ns();result=self.result(reply,key)
            result['match_finished_monotonic_ns']=finished
            result['recognized_at']=now()
            after=None
            try:after=self.stats(key)
            except Exception:pass
            verified=bool(after and after['current_credit_balance']==0 and after['credits_spent']==0 and details['before']['credits_spent']==0)
            self.store.set_setting('online_locked',not verified)
            result.update(before=details.get('before'),after=after,zero_cost_verified=verified,cost_yuan=0 if verified else None,
                online_elapsed_s=max(0,time.time()-details['request_started_wall']) if 'request_started_wall' in details else None,
                preprocessing=details.get('preprocessing'))
            self.store.save_online(identifier,details['wav_sha256'],'done',token=token,details={**details,'result':result})
            self.audit('audiotag_completed',job_id=identifier,matched=result['matched'],before=details.get('before'),after=after,zero_cost_verified=verified)
            return result
        self.store.set_setting('online_locked',True)
        return self.failure('online_timeout',before=details.get('before'),pending_job_id=identifier,can_resume=True)
    @staticmethod
    def failure(reason,**extra):return {'matched':False,'source':'none','reason':reason,'message':REASONS.get(reason,'未在本地歌单找到'),**extra}
    @staticmethod
    def result(reply,key):
        if reply.get('result')=='not found':return AudioTagClient.failure('online_not_found')
        if reply.get('result')!='found':return AudioTagClient.failure('online_error')
        groups=reply.get('data',[]);candidates=[]
        for group in groups if isinstance(groups,list) else []:
            if not isinstance(group,dict):continue
            confidence=group.get('confidence')
            if isinstance(confidence,bool) or not isinstance(confidence,(int,float)) or not math.isfinite(confidence) or not 0<=confidence<=100:continue
            for track in group.get('tracks',[]):
                if not isinstance(track,list) or len(track)<2 or not all(isinstance(v,str) for v in track[:2]):continue
                title,artist=(str(v).replace(key,'[REDACTED]')[:400] for v in track[:2])
                if title.strip() and artist.strip():candidates.append({'title':title,'artist':artist,'confidence':confidence})
        if not candidates:return AudioTagClient.failure('online_not_found')
        best=max(float(r['confidence']) for r in candidates);top={}
        for candidate in candidates:
            if float(candidate['confidence'])!=best:continue
            identity=online_song_identity(candidate['title'],candidate['artist']);previous=top.get(identity)
            if previous is None or len(candidate['title'])<len(previous['title']):top[identity]=candidate
        if len(top)!=1:return {**AudioTagClient.failure('ambiguous_online'),'candidates':candidates}
        row=next(iter(top.values()))
        return {'matched':True,'source':'audiotag','reason':'matched',**row,'candidates':candidates}
