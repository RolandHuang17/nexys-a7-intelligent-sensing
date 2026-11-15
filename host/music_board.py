"""UART-side music workflow, called only by the existing serial owner thread."""
import json,time,uuid
from pathlib import Path
from audit import ROOT,write_json,now
from capture import checked
from music_protocol import configure,abort,music_status,export,finish,acknowledge
from music_store import MusicStore

class MusicCancelled(Exception):
    """An addressed cancellation interrupted a synchronous PCM export."""

def knock_settings(values):
    # Accepted older profiles used 50/20, below this board's quiet L1 noise
    # (observed max 206). Keep the detector itself intact; require a clear hit.
    high=max(300,int(values['high']));low=min(high-1,max(80,int(values['low'])))
    return {**values,'high':high,'low':low,'wake':True}

class MusicBoard:
    def __init__(self,service):
        self.s=service;self.enabled=False;self.policy='auto';self.settings={'seconds':10,'high':300,'low':80,'wake':True,'game':False,'min_ms':150,'max_ms':1000}
        self.current=None;self.result=None;self.last=None;self.last_poll=0;self.center_seen=None;self.restore=None;self.exit_pending=False
        self.store=MusicStore();self.stage='idle';self.clock=None;self.pending_settings=None;self.verify_repeat=False;self.key_quiet_until=0;self.wake_muted=False;self.cancel_waiting=None
    def emit(self,kind,**data):
        try:self.s.panel.on_music_message(kind,data,self)
        except Exception as error:self.s.run_record.event('panel_projection_ignored',kind=kind,error=repr(error))
        self.s.emit(kind,**data)
    def control(self,action,args,d):
        if not action.startswith('music_'):return False
        if action=='music_enable':
            if self.cancel_waiting is not None:raise RuntimeError('请等待中止完成')
            if self.current:raise RuntimeError('请等待本次识曲完成')
            self.settings=knock_settings({**self.settings,**{k:args[k] for k in self.settings if k in args}});self.policy=args.get('policy',self.policy)
            self.verify_repeat=bool(args.get('verify_repeat',False))
            if not self.enabled:
                self.restore={'armed':bool(self.s.last and self.s.last.get('armed')),'mode':int(self.s.last['mode']) if self.s.last else 3}
                checked(d.request('ARM',bytes((self.restore['mode'],0))))
            # A previous interrupted job may already have been fully exported.
            prior=music_status(d)
            if prior['state']==0 and prior['flags']&8:finish(d)
            if prior['state'] in (1,2,3):
                self.pending_settings=dict(self.settings)
                self.settings={**self.settings,'seconds':prior['target_samples']//prior['sample_rate'],'game':False}
                row=prior
            else:
                row=configure(d,enabled=True,**{**self.settings,'wake':False})
                self.wake_muted=True;self.key_quiet_until=time.monotonic()+self.settings['max_ms']/1000+.2
            self.enabled=True;self.last=row;self.center_seen=row['center_seq'];self.exit_pending=False
            self.emit('music_mode',enabled=True,settings=self.settings,policy=self.policy,text='进入识曲，稍等就绪后连续敲桌三下才开始录音。')
            if self.pending_settings:
                self.emit('music_notice',text='发现板上未读完的录音，先恢复为仅离线任务，保留原编号并重新完整校验。')
                self.begin(row,recovered=True)
        elif action=='music_disable':
            if self.current:self.exit_pending=True;self.emit('music_notice',text='本次任务完成后退出识曲；暂不开始下一条。')
            else:self.disable(d)
        elif action=='music_policy':
            if self.enabled:self.step(d,force=True,allow_export=False)
            self.policy=args['policy'];self.emit('music_policy',policy=self.policy,current_policy=self.current['policy'] if self.current else None)
        elif action=='music_start':
            if not self.enabled:raise RuntimeError('请先启用识曲')
            if self.current:raise RuntimeError('本次录音尚未完成，请稍候')
            self.emit('music_notice',text='已进入等待：连续敲桌三下才开始录音。')
        elif action=='music_settings':
            wanted=knock_settings({**self.settings,**{k:args[k] for k in self.settings if k in args}})
            if self.current:self.pending_settings=wanted
            else:
                self.settings=wanted
                if self.enabled:self.last=configure(d,enabled=True,**{**self.settings,'wake':not self.wake_muted and self.cancel_waiting is None})
            self.emit('music_notice',text='录音设置从下一次任务生效。')
        elif action=='music_cancel_ready':
            if self.cancel_waiting==args.get('job_id'):
                self.cancel_waiting=None
                self.key_quiet_until=time.monotonic()+self.settings['max_ms']/1000+.2
                self.emit('music_cancel_ready',job_id=args['job_id'],enabled=self.enabled)
        elif action=='music_idle_result':
            if self.current is None and self.cancel_waiting is None:
                self.result=args['result']
                from panel_control import result_phase
                phase=result_phase(self.result)
                if self.s.panel.update(phase,job_id=self.result.get('job_id'),value=1 if int(phase)==6 else 0):self.s.panel.finished=True
        elif action=='music_result':
            if not self.current or args['result'].get('job_id')!=self.current['id']:return True
            self.result=args['result'];self.stage='result';self.current['result']=self.result
            if self.current['game']:
                self.emit('music_game_ready',job=self.current,result=self.result,clock=self.clock,status=self.last)
            else:self.complete(d)
        elif action=='music_game_reveal':
            if not self.current or not self.current['game'] or not self.result:raise RuntimeError('机器尚未取得结果')
            row=music_status(d);self.last=row
            clock=self.current.get('clock') or self.clock
            elapsed=(self.result['match_finished_monotonic_ns']-clock['start_host_estimate_ns'])/1e9
            human=(row['human_tick']-row['start_tick'])/1e8 if row['human_tick'] else None
            error=clock['uncertainty_ns']/1e9+.006
            record={'round_id':self.current['id'],'start_tick':row['start_tick'],'human_tick':row['human_tick'],
                'human_s':human,'machine_s':elapsed,'clock_uncertainty_s':error,'human_answer':args.get('answer',''),
                'machine_result':self.result,'revealed_at':now(),'timing':'board tap timestamp; actual worker match completion; same start mapping'}
            self.current['game_result']=record
            song=self.store.record_result(self.current['id'],self.result,'offline',self.current['metadata']['wav'],self.result['wav_sha256'],record)
            self.result['song_id']=song
            with self.store.db() as c:c.execute('INSERT OR REPLACE INTO games VALUES(?,?)',(record['round_id'],json.dumps(record,ensure_ascii=False)))
            write_json(Path(self.current['directory'])/'game.json',record);self.emit('music_game_revealed',record=record);self.complete(d)
        else:raise ValueError('未知识曲控制操作')
        return True
    def cancel(self,d,job_id):
        job=self.current
        if (job is not None and job['id']!=job_id) or (self.cancel_waiting is not None and self.cancel_waiting!=job_id):
            # A late cancel for a retried/previous job cannot touch a new capture.
            self.emit('music_cancelled',job_id=job_id,reason='user_cancelled',enabled=self.enabled,ignored=True,text='旧任务已结束。')
            return
        retry=self.cancel_waiting==job_id
        self.cancel_waiting=job_id  # Quarantine before UART, including uncertain acknowledgements.
        saved=None;stage=self.stage
        if retry:
            # A failed CONFIG/ACK may leave wake enabled. Any capture created
            # inside this quarantine belongs to no new GUI job and is discarded.
            row=music_status(d)
            if row['state'] or row['flags']&8:row=abort(d,row['record_id'])
            if row['state']!=0 or row['flags']&8:raise RuntimeError('板端尚未确认中止')
            self.last=row
        elif job is not None:
            row=abort(d,job['record_id'])
            if row['state']!=0 or row['flags']&8:raise RuntimeError('板端尚未确认中止')
            self.last=row
        if job is not None:
            metadata=job.get('metadata') or {}
            if metadata.get('wav') and Path(metadata['wav']).is_file():saved=metadata['wav']
            directory=Path(job['directory']);directory.mkdir(parents=True,exist_ok=True)
            write_json(directory/'cancelled.json',{'time':now(),'job_id':job_id,'record_id':job['record_id'],
                'stage':stage,'reason':'user_cancelled','saved_wav':saved})
        # A local WAV retry has no live board recording, but needs the same ACK.
        self.current=None;self.result=None;self.stage='idle';self.cancel_waiting=job_id
        if self.pending_settings:self.settings={**self.pending_settings,'wake':True};self.pending_settings=None
        if self.exit_pending:self.disable(d)
        elif self.enabled:
            self.last=configure(d,enabled=True,**{**self.settings,'wake':False})
            self.wake_muted=True;self.key_quiet_until=time.monotonic()+self.settings['max_ms']/1000+.2
        self.s.run_record.event('music_job_cancelled',job_id=job_id,stage=stage,saved_wav=saved)
        self.emit('music_cancelled',job_id=job_id,reason='user_cancelled',enabled=self.enabled,saved_wav=saved,
            text='已中止本次识曲；稍等就绪后可重新敲三下。' if self.enabled else '已中止本次识曲，已退出。')
    def disable(self,d):
        if self.enabled:
            row=music_status(d)
            if row['state']==0:
                if row['flags']&8:finish(d)
                configure(d,enabled=False,**self.settings)
                self.enabled=False
                if self.restore and self.restore['armed']:checked(d.request('ARM',bytes((self.restore['mode'],1))))
                self.emit('music_mode',enabled=False,text='已恢复原实时监测和事件功能。')
    def reconnected(self,d):
        if not self.enabled:return
        row=music_status(d);self.last=row
        if self.current and row['record_id']==self.current['record_id'] and row['state'] in (1,2,3):
            self.stage='recording'
            self.s.run_record.event('music_read_resumed',job_id=self.current['id'],record_id=row['record_id'],state=row['state'])
            self.emit('music_notice',text='已重新连接，保留原录音编号，重新完整读回并校验。')
        elif self.current and row['state']==0 and not row['flags']&8:
            self.s.run_record.event('music_recording_lost_after_reset',job_id=self.current['id'],status=row)
            identifier=self.current['id'];self.current=None;self.result=None;self.stage='idle'
            self.emit('music_cancelled',job_id=identifier,enabled=self.enabled,reason='board_reset',text='开发板已复位，板上未完成录音已丢失；已保存的WAV仍在本机。')
            configure(d,enabled=True,**{**self.settings,'wake':self.cancel_waiting is None})
    def begin(self,row,recovered=False):
        if self.current:return
        identifier=uuid.uuid4().hex
        directory=self.s.run_record.path/'music'/f'e{self.s.epoch}_record{row["record_id"]}_{identifier[:8]}'
        self.current={'id':identifier,'record_id':row['record_id'],'policy':'offline' if self.settings['game'] or recovered else self.policy,
            'game':self.settings['game'] and not recovered,'recovered':recovered,'verify_repeat':self.verify_repeat,'directory':str(directory),'clock':self.clock,'start_status':row}
        self.result=None;self.stage='recording';self.center_seen=row['center_seq']
        self.s.run_record.event('music_job_started',**self.current)
        self.emit('music_started',job=self.current)
    def complete(self,d):
        finish(d);job=self.current
        self.s.run_record.event('music_job_finished',job_id=job['id'],source=self.result.get('source'),matched=self.result.get('matched'))
        self.current=None;self.stage='idle'
        if self.pending_settings:
            self.settings=self.pending_settings;self.pending_settings=None
            configure(d,enabled=True,**self.settings)
        if self.exit_pending:self.disable(d)
        self.emit('music_complete',job=job,result=self.result)
    def step(self,d,force=False,allow_export=True):
        if not self.enabled:return
        if self.cancel_waiting is not None:return
        if not force and time.monotonic()-self.last_poll<.1:return
        self.last_poll=time.monotonic();before=time.perf_counter_ns();row=music_status(d);after=time.perf_counter_ns();self.last=row
        if row['state'] in (1,2,3) and self.current is None:
            # For autonomous triple-knock starts, reconstruct t0 from a timestamped request bracket.
            self.clock={'request_before_ns':before,'request_after_ns':after,'board_tick':row['tick'],'start_board_tick':row['start_tick'],
                'start_host_estimate_ns':(before+after)//2-int((row['tick']-row['start_tick'])*10),'uncertainty_ns':(after-before)//2}
            self.begin(row)
        self.emit('music_status',status=row,job_id=self.current['id'] if self.current else None,stage=self.stage)
        if row['center_seq']!=self.center_seen:
            self.center_seen=row['center_seq']
            if self.current is None and row['state']==0 and self.settings['wake']:
                configure(d,enabled=True,**{**self.settings,'wake':False});self.wake_muted=True;self.key_quiet_until=time.monotonic()+self.settings['max_ms']/1000+.2
            if self.result and self.result.get('matched') and not (self.current and self.current['game']):
                song=self.result.get('song_id') or self.store.put_song(self.result['title'],self.result['artist']);self.store.favourite(song)
                self.s.run_record.event('music_centre_favourite',song_id=song,center_tick=row['center_tick'],center_seq=row['center_seq'])
                self.emit('music_favourite',song_id=song,text='已收藏；重复按中键不会增加副本。')
        if self.wake_muted and self.cancel_waiting is None and time.monotonic()>=self.key_quiet_until and self.current is None and row['state']==0 and not (self.s.last or {}).get('buttons',0)&16:
            configure(d,enabled=True,**self.settings);self.wake_muted=False
            if self.settings['wake']:self.emit('music_notice',text='已就绪：连续敲桌三下开始录音。')
        if allow_export and self.current and row['state']==3 and self.stage=='recording':
            job=self.current;self.stage='transferring';self.s.fft_job=None;last_update=0
            self.emit('music_progress',stage=self.stage,current=0,total=row['samples'],job=self.current)
            def progress(n,total):
                nonlocal last_update
                self.s.cancel_hook(d)
                if self.current is not job or self.cancel_waiting is not None:raise MusicCancelled()
                if self.s.stop_event.is_set():raise InterruptedError('录音冻结在板上，等待重新连接')
                if time.monotonic()-last_update>.2:
                    last_update=time.monotonic();self.emit('music_progress',stage='transferring',current=n,total=total,job=self.current);self.s.poll(d,force=True)
                if self.current is not job or self.cancel_waiting is not None:raise MusicCancelled()
            directory=Path(self.current['directory']);directory.mkdir(parents=True,exist_ok=True)
            attempt=directory/f'read_{len(list(directory.glob("read_*")))+1:02}';attempt.mkdir()
            try:
                metadata=export(d,row,attempt/'first',ack=False,on_progress=progress,programming=self.s.programming)
                self.current['metadata']=metadata  # Retain a verified first WAV if a repeat read is cancelled.
                if self.current['verify_repeat']:
                    self.emit('music_notice',text='验收读回：正在第二次完整读取同一段冻结录音。')
                    repeated=export(d,row,attempt/'repeat',ack=False,on_progress=progress,programming=self.s.programming)
                    if repeated['pcm_sha256']!=metadata['pcm_sha256']:raise ValueError('同一录音重复读回不一致，保留板上原件')
                    metadata.update(repeat_equal=True,repeat_metadata=repeated,total_transfer_s=metadata['export_s']+repeated['export_s'])
                acknowledge(d,row)
                metadata.update(job_id=self.current['id'],policy=self.current['policy'],clock=self.current['clock'])
                self.current['metadata']=metadata;write_json(Path(self.current['directory'])/'metadata.json',metadata)
                self.stage='matching';self.s.run_record.event('music_recording_verified',job_id=self.current['id'],samples=metadata['samples'],crc32=metadata['crc32'],wav_sha256=metadata['wav_sha256'],export_s=metadata['export_s'])
                self.emit('music_exported',job=self.current,metadata=metadata)
            except MusicCancelled:
                return
