"""One isolated worker for audfprint/HTTP; serial never enters this process."""
import json,sys,time,traceback,uuid
from pathlib import Path
from audit import ROOT,Run,sha256,write_json,now
from music_library import LocalMatcher,import_tracks
from music_shazam import ShazamOnlineClient
from music_store import MusicStore

def recognize_recording(identifier,wav,mode,store,matcher,*,audit=None,online=None,game=False,metadata=None):
    """Automatic tasks try ShazamIO first; offline tasks retain the local path."""
    wav=Path(wav);assert mode in ('auto','offline')
    local={'matched':False,'not_run':True,'reason':'online_priority_succeeded'}
    online_result=None
    if mode=='auto':
        online_result=(online or ShazamOnlineClient(store,audit=audit)).recognize(identifier,wav,mode)
    if online_result and online_result.get('matched'):
        result=dict(online_result)
    else:
        local=matcher.match(wav);local_finished=time.perf_counter_ns();result=dict(local)
        result['match_finished_monotonic_ns']=local_finished
        if online_result is not None:
            result['online_attempt']=online_result
            for key in ('cost_yuan','paid_service_calls','key_accesses','online_elapsed_s','preprocessing','provider'):
                if key in online_result:result[key]=online_result[key]
            reason=online_result.get('message','在线识别未完成')
            if local.get('matched'):result['message']='在线未能确定歌名，已由本地歌单匹配。'+reason
            else:
                result['reason']=online_result.get('reason','online_error')
                result['message']=('本地歌单和在线曲库都未匹配' if result['reason']=='online_not_found' else '本地歌单未匹配；'+reason)
        elif not local.get('matched'):result['message']='未在本地歌单找到'
    result['local_evidence']=local
    result['recognition_order']='online_first' if mode=='auto' else 'offline_only'
    result.setdefault('match_finished_monotonic_ns',time.perf_counter_ns())
    result.setdefault('recognized_at',now())
    result['job_id']=identifier;result['mode']=mode;result['wav_sha256']=sha256(wav);result['wav']=str(wav)
    if not game:result['song_id']=store.record_result(identifier,result,mode,wav,sha256(wav),metadata,
        update_pending=False)
    return result,local

def serve():
    # A windowed PyInstaller process may set the Python streams to None even
    # though its parent supplied valid Windows pipe handles.
    if sys.stdin is None or sys.stdout is None:
        import os,ctypes,msvcrt
        k=ctypes.WinDLL('kernel32',use_last_error=True);k.GetStdHandle.restype=ctypes.c_void_p
        if sys.stdin is None:
            fd=msvcrt.open_osfhandle(k.GetStdHandle(-10),os.O_RDONLY)
            sys.stdin=os.fdopen(fd,'r',encoding='utf8')
        if sys.stdout is None:
            fd=msvcrt.open_osfhandle(k.GetStdHandle(-11),os.O_WRONLY)
            sys.stdout=os.fdopen(fd,'w',encoding='utf8',buffering=1)
        if sys.stderr is None:sys.stderr=open(os.devnull,'w',encoding='utf8')
    store=MusicStore();matcher=LocalMatcher();out=sys.stdout
    for line in sys.stdin:
        request=None
        try:
            request=json.loads(line);identifier=request.get('id') or uuid.uuid4().hex;action=request['action'];r=Run('music_'+action)
            r.event('music_worker_started',action=action,job_id=identifier,mode=request.get('mode'))
            if action=='import':result=import_tracks(request['tracks']);matcher=LocalMatcher()
            elif action=='calibrate':
                import contextlib,io
                from tune_music_profile import main
                with contextlib.redirect_stdout(io.StringIO()):result=main(request['data'])
            elif action=='verify':result=ShazamOnlineClient.failure('offline_only') if request.get('mode')=='offline' else ShazamOnlineClient(store,audit=r.event).verify()
            elif action=='match':
                def progress(kind,**fields):
                    r.event(kind,**fields)
                    if kind in ('shazam_request','shazam_wait'):
                        text='正在通过Shazam识别板载麦克风录音' if kind=='shazam_request' else f'遵守服务请求间隔，约{fields["seconds"]:.0f}秒后开始识别'
                        out.write(json.dumps({'id':identifier,'action':'match_progress','ok':True,'message':text},ensure_ascii=False)+'\n');out.flush()
                result,local=recognize_recording(identifier,request['wav'],request['mode'],store,matcher,audit=progress,
                    game=request.get('game',False),metadata=request.get('metadata'))
                write_json(r.path/'local_evidence.json',local)
            else:raise ValueError('未知识曲工作指令')
            result['worker_run_id']=r.run_id;write_json(r.path/'result.json',result);r.event('music_worker_completed',action=action,job_id=identifier);r.manifest()
            out.write(json.dumps({'id':identifier,'action':action,'ok':True,'result':result},ensure_ascii=False)+'\n');out.flush()
        except Exception as error:
            # Key-bearing objects and HTTP responses are never rendered here.
            record={'id':(request or {}).get('id'),'action':(request or {}).get('action'),'ok':False,'error':type(error).__name__,'message':'操作未完成，原文件保留；请查看本机诊断记录。'}
            if request and request.get('action')!='verify':
                r.event('music_worker_failed',error_type=type(error).__name__);write_json(r.path/'failure.json',record);r.manifest()
            out.write(json.dumps(record,ensure_ascii=False)+'\n');out.flush()

class MusicEngine:
    """Own a replaceable worker generation; cancellation never touches saved audio."""
    def __init__(self,publish):
        import threading
        self.publish=publish;self.lock=threading.RLock();self._generation=0;self._closed=False
        self._pending={};self._cancelled=set();self._cancel_waiters=set();self._deferred=[];self._restarting=False
        with self.lock:self._spawn_locked()

    def _spawn_locked(self):
        import subprocess,threading,os
        from app_paths import app_command
        process=subprocess.Popen(app_command('--internal-music-worker'),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,encoding='utf8',bufsize=1,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.process=process;generation=self._generation
        threading.Thread(target=self._reader,args=(process,generation),name='music-results',daemon=True).start()
        threading.Thread(target=self._drain,args=(process,),name='music-stderr',daemon=True).start()

    def _reader(self,process,generation):
        try:
            for line in process.stdout:
                try:message=json.loads(line)
                except (ValueError,TypeError):continue
                if not isinstance(message,dict):continue
                with self.lock:
                    if self._closed or generation!=self._generation:continue
                    identifier=message.get('id')
                    if identifier in self._cancelled:continue
                    if message.get('action')!='match_progress':self._pending.pop(identifier,None)
                    self.publish(message)
        finally:
            with self.lock:
                if not self._closed and generation==self._generation:
                    self.publish({'action':'worker_exit','ok':False,'message':'识曲工作进程已停止，请重新打开软件。'})
            try:process.stdout.close()
            except Exception:pass

    @staticmethod
    def _drain(process):
        # Capture the process, not self.process: a replacement owns different pipes.
        try:
            for _ in process.stderr:pass
        finally:
            try:process.stderr.close()
            except Exception:pass

    def submit(self,action,**values):
        identifier=values.pop('id',uuid.uuid4().hex);request={'id':identifier,'action':action,**values}
        with self.lock:
            if self._closed:raise RuntimeError('Music worker is closed')
            if identifier in self._cancelled:return identifier
            self._pending[identifier]=action
            if self._restarting:self._deferred.append(request)
            else:
                try:self.process.stdin.write(json.dumps(request,ensure_ascii=False)+'\n');self.process.stdin.flush()
                except Exception:self._pending.pop(identifier,None);raise
        return identifier

    def cancel(self,identifier):
        """Return immediately; publish a matching acknowledgement when ready."""
        import threading
        with self.lock:
            if self._closed:return
            self._cancelled.add(identifier)
            self._deferred=[r for r in self._deferred if r['id']!=identifier]
            if self._restarting:
                self._pending.pop(identifier,None);self._cancel_waiters.add(identifier);return
            if self._pending.get(identifier)!='match':
                self.publish({'id':identifier,'action':'cancelled','ok':True,'worker_restarted':False});return
            self._generation+=1;self._pending.clear();self._restarting=True;self._cancel_waiters.add(identifier)
            process=self.process;generation=self._generation
        threading.Thread(target=self._finish_cancel,args=(process,generation),name='music-cancel',daemon=True).start()

    def _finish_cancel(self,process,generation):
        error=None;stopped=False
        try:
            from pc_shazam_backend import terminate_owned_worker
            terminate_owned_worker(process)  # Includes frozen bootloader and nested HTTP child on Windows.
            process.wait(timeout=5);stopped=True
            try:process.stdin.close()
            except Exception:pass
        except Exception as caught:error=type(caught).__name__
        with self.lock:
            if self._closed or generation!=self._generation:return
            if error is None:
                try:
                    self._spawn_locked()
                    deferred=self._deferred;self._deferred=[]
                    for request in deferred:
                        if request['id'] in self._cancelled:continue
                        self.process.stdin.write(json.dumps(request,ensure_ascii=False)+'\n')
                    self.process.stdin.flush()
                except Exception as caught:error=type(caught).__name__
            # Keep flush and readiness atomic so a concurrent submit is not stranded.
            self._restarting=False;waiters=self._cancel_waiters;self._cancel_waiters=set()
            if error:self._pending.clear();self._deferred.clear()
            for identifier in waiters:
                reply={'id':identifier,'action':'cancelled','ok':error is None,'worker_restarted':error is None}
                if error:reply.update(error_type=error,message=('本次已中止，识曲组件未能恢复，请重新打开软件；已保存录音保留。' if stopped else '未能确认识曲进程已停止，请关闭软件后重试；已保存录音保留。'))
                self.publish(reply)

    def close(self):
        with self.lock:
            self._closed=True;self._generation+=1;self._deferred.clear();self._pending.clear();self._cancel_waiters.clear()
            try:self.process.stdin.close()
            except Exception:pass
